"""E&R PokerBet — FastAPI application (single service, single port).

Routes:
    GET  /api/health                → liveness
    POST /api/snapshot              → PokerBet scraper ingestion
    GET  /api/tables                → all table views (dashboard)
    GET  /api/table/{table_id}      → one table view (player+browser query)
    POST /api/commands              → operator queues an action
    GET  /api/commands/pending      → browser polls for its next command
    POST /api/commands/ack          → browser confirms execution
    GET  /api/commands              → list (status filter)
    POST /api/equity                → in-process eval7 calculation
    GET  /api/events                → SSE live stream
    GET  /                          → unified dashboard (static)
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .command_queue import CommandQueue
from .config import settings
from .db import init_db, session
from .equity import calculate
from .players.db import PlayerDatabase
from .players.identity import IdentityService
from .schemas import CommandAck, CommandCreate, CommandView, EquityRequest, EquityResult, PlayerView, SnapshotPayload, TableView
from .state import StaleSnapshotError, StateStore

# ── in-process event bus → SSE fanout (single service, no extra hops) ─────
_subscribers: set[asyncio.Queue] = set()


def publish(event_type: str, scope: str, payload: dict) -> None:
    msg = json.dumps({"type": event_type, "scope": scope, "payload": payload})
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


# ── auth ───────────────────────────────────────────────────────────────────
def require_api_key(x_api_key: str = Header(default="")) -> None:
    expected = settings.effective_api_key()
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid API key")


# ── wiring ─────────────────────────────────────────────────────────────────
def _services():
    players_db = PlayerDatabase(settings.players_db)
    identity = IdentityService(players_db)
    return StateStore(identity), CommandQueue()


# ── health ─────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    with session() as s:
        from sqlalchemy import text

        db_ok = s.execute(text("SELECT 1")).scalar() == 1
    return {"status": "ok", "app": settings.app_name, "db": "ok" if db_ok else "error"}


# ── snapshot ingestion ─────────────────────────────────────────────────────
@app.post("/api/snapshot", response_model=TableView)
def post_snapshot(payload: SnapshotPayload, _auth: None = Depends(require_api_key)):
    store, _ = _services()
    try:
        view = store.process_snapshot(payload)
    except StaleSnapshotError as e:
        raise HTTPException(status_code=409, detail=e.reason)
    except (PermissionError, ValueError, KeyError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    publish("table", view.scope_key, {"table_id": view.table_id, "version": view.snapshot_version})
    return view


# ── tables ─────────────────────────────────────────────────────────────────
@app.get("/api/tables", response_model=list[TableView])
def tables(_auth: None = Depends(require_api_key)):
    store, _ = _services()
    return store.list_tables()


@app.get("/api/table/{table_id}", response_model=TableView)
def table(table_id: str, player_id: str = Query(...), browser_instance_id: str = Query(...), _auth: None = Depends(require_api_key)):
    store, _ = _services()
    view = store.get_table(player_id, browser_instance_id, table_id)
    if view is None:
        raise HTTPException(status_code=404, detail="table not found")
    return view


# ── commands ───────────────────────────────────────────────────────────────
@app.post("/api/commands", response_model=CommandView)
def create_command(req: CommandCreate, _auth: None = Depends(require_api_key)):
    _, queue = _services()
    try:
        cmd = queue.create(req)
    except (ValueError, PermissionError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    publish("command", cmd.player_id, {"command_id": cmd.command_id, "action": cmd.action, "status": cmd.status})
    return cmd


@app.get("/api/commands", response_model=list[CommandView])
def list_commands(status: str | None = None, _auth: None = Depends(require_api_key)):
    _, queue = _services()
    return queue.list(status=status)


@app.get("/api/commands/pending", response_model=CommandView | None)
def pending(player_id: str = Query(...), browser_instance_id: str = Query(...), _auth: None = Depends(require_api_key)):
    _, queue = _services()
    try:
        return queue.claim_next(player_id, browser_instance_id)
    except (PermissionError, KeyError) as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.post("/api/commands/ack", response_model=CommandView)
def ack_command(ack: CommandAck, _auth: None = Depends(require_api_key)):
    _, queue = _services()
    try:
        return queue.ack(ack.command_id, ack.player_id, ack.browser_instance_id, ack.status, ack.error)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ── equity ─────────────────────────────────────────────────────────────────
@app.post("/api/equity", response_model=EquityResult)
def equity(req: EquityRequest, _auth: None = Depends(require_api_key)):
    result = calculate(req)
    publish("equity", "global", {
        "results": [r.model_dump() for r in result.results],
        "error": result.error,
    })
    return result


# ── SSE live events ────────────────────────────────────────────────────────
@app.get("/api/events")
async def sse_events(_auth: None = Depends(require_api_key)) -> StreamingResponse:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)

    async def gen() -> AsyncGenerator[str, None]:
        try:
            # replay recent events from DB so a reconnecting dashboard catches up
            with session() as s:
                from .models import Event
                from sqlalchemy import select

                for ev in s.execute(select(Event).order_by(Event.id.desc()).limit(50)).scalars().all():
                    yield f"event: {ev.type}\ndata: {ev.payload}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── players (metadata only — NEVER credentials) ───────────────────────────
@app.get("/api/players", response_model=list[PlayerView])
def players(_auth: None = Depends(require_api_key)):
    db = PlayerDatabase(settings.players_db)
    try:
        return [PlayerView(**p.to_dict()) for p in db.list_players()]
    finally:
        db.close()


# ── dashboard ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(__import__("pathlib").Path(__file__).resolve().parent / "static")), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(__import__("pathlib").Path(__file__).resolve().parent / "static" / "index.html"))
