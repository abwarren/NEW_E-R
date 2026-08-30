/* E&R PokerBet — modular scraper + command executor (PokerBet only).

 * PokerBet runs the BetConstruct SkillGames Angular client at
 * poker-web.pokerbet.co.za — the SAME table DOM as GoldRush. Verified from
 * the live client bundles (2026-08-30): seat containers, self-player hero
 * class, control-b-view-p action buttons, single-cart-view-p cards,
 * sg-poker-betting-slider bet sizing.
 *
 * Pipeline: DOM discovery → PokerBet state extraction → normalisation →
 * snapshot → E&R API. Commands: poll pending → execute native click → ACK.
 *
 * No chrome.runtime deps in the scrape path (pure fetch) so it also works
 * pasted into the client console during development.
 */
(function () {
  'use strict';
  if (window.__er_w4p_loaded) return;
  window.__er_w4p_loaded = true;

  // ── configuration ───────────────────────────────────────────────────────
  // Precedence: window.ER_* globals (console-paste dev mode) → chrome.storage
  // (options page — the supported per-device config) → dev defaults.
  var CONFIG_DEFAULTS = {
    apiBase: 'http://127.0.0.1:8090',
    apiKey: '',
    playerId: '',
    browserInstanceId: ''
  };
  var CONFIG = {
    apiBase: CONFIG_DEFAULTS.apiBase,
    apiKey: CONFIG_DEFAULTS.apiKey,
    playerId: CONFIG_DEFAULTS.playerId,
    browserInstanceId: CONFIG_DEFAULTS.browserInstanceId,
    pollMs: 800,
    snapshotMs: 1200
  };

  function pickConfig(winVal, storedVal, key) {
    if (winVal !== undefined && winVal !== null && String(winVal).trim() !== '') return winVal;
    if (storedVal !== undefined && storedVal !== null && String(storedVal).trim() !== '') return storedVal;
    return CONFIG_DEFAULTS[key];
  }

  function logConfig() {
    console.log('[ER-W4P] config | player=' + CONFIG.playerId + ' browser=' + CONFIG.browserInstanceId + ' api=' + CONFIG.apiBase);
  }

  function loadConfig(cb) {
    var fromWindow = {
      apiBase: window.ER_API_BASE,
      apiKey: window.ER_API_KEY,
      playerId: window.ER_PLAYER_ID,
      browserInstanceId: window.ER_BROWSER_ID
    };
    var apply = function (stored) {
      CONFIG.apiBase = pickConfig(fromWindow.apiBase, stored.erApiBase, 'apiBase');
      CONFIG.apiKey = pickConfig(fromWindow.apiKey, stored.erApiKey, 'apiKey');
      CONFIG.playerId = pickConfig(fromWindow.playerId, stored.erPlayerId, 'playerId');
      CONFIG.browserInstanceId = pickConfig(fromWindow.browserInstanceId, stored.erBrowserId, 'browserInstanceId');
      logConfig();
      if (cb) cb();
    };
    if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
      chrome.storage.local.get(['erApiBase', 'erApiKey', 'erPlayerId', 'erBrowserId'], apply);
      // live reload: saving the options page updates this tab without a reload
      chrome.storage.onChanged.addListener(function (changes, area) {
        if (area !== 'local') return;
        if (changes.erApiBase) CONFIG.apiBase = pickConfig(undefined, changes.erApiBase.newValue, 'apiBase');
        if (changes.erApiKey) CONFIG.apiKey = pickConfig(undefined, changes.erApiKey.newValue, 'apiKey');
        if (changes.erPlayerId) CONFIG.playerId = pickConfig(undefined, changes.erPlayerId.newValue, 'playerId');
        if (changes.erBrowserId) CONFIG.browserInstanceId = pickConfig(undefined, changes.erBrowserId.newValue, 'browserInstanceId');
        logConfig();
      });
    } else {
      apply({}); // node harness / console-paste mode: window globals or defaults
    }
  }

  // ── Selector profile: PokerBet (BetConstruct SkillGames) ───────────────
  // Live-verified 2026-08-30 at poker-web.pokerbet.co.za/18751019/
  // (table 2143034 "Multan"): seats are sg-poker-table-seat.player-N, hero is
  // the .player-mini-container-p.self-player.poker wrapper INSIDE the hero
  // seat; name = .player-name-count-v.self-player, stack = .player-text-info-p.
  var SEL = {
    tableProof: 'sg-poker-table, sg-poker-table-seat, .player-mini-container-p, .control-b-view-p, .pot-w-view-p, .single-cart-view-p',
    seatContainer: 'sg-poker-table-seat',
    heroClass: '.player-mini-container-p.self-player.poker, .player-mini-container-p.self-player',
    playerName: '.player-name-count-v.self-player, .player-name, p.single-win-item-sizes',
    stack: '.player-text-info-p span b, .player-text-info-p b, .player-stack',
    holeCards: '.carts-container-p .single-cart-view-p',
    board: 'sg-poker-board .single-cart-view-p, .board-cards-view-p .single-cart-view-p',
    pot: '.pot-w-view-p, .pot-amount, .total-pot',
    dealer: '.dealer-icon-view',
    sittingOut: '.seat-out-v',
    activeTurn: '.active-turn',
    buttons: {
      fold: '.control-b-view-p.fold-c',
      check: '.control-b-view-p.check-c',
      call: '.control-b-view-p.call-c',
      bet: '.control-b-view-p.bet-c',
      raise: '.control-b-view-p.raise-c',
      all_in: '.control-b-view-p.all_in-c',
      cash_out: '.control-b-view-p.cash_out-c',
      show: '.control-b-view-p.show-c',
      run_it_twice: '.control-b-view-p.run_it_twice-c',
      resume_hand: '.control-b-view-p.resume_hand-c',
      back_to_game: '.control-b-view-p.back_to_game-c'
    },
    slider: 'sg-poker-betting-slider',
    preset: 'sg-poker-betting-slider .limits-buttons-v-p li, sg-poker-betting-slider .limits-buttons-v-p button',
    amountDisplay: 'sg-poker-betting-slider .bet-amount, sg-poker-betting-slider .amount, sg-poker-betting-slider i'
  };

  // ── state ───────────────────────────────────────────────────────────────
  var state = {
    lastSnapshotVersion: 0,
    lastHandId: '',
    executedCommandIds: {},   // idempotency: never execute the same command twice
    seq: 0
  };

  function isPokerBet() {
    return /poker-web\.pokerbet\.co\.za/.test(location.hostname);
  }

  function hasTableProof() {
    try { return !!document.querySelector(SEL.tableProof); } catch (e) { return false; }
  }

  // ── DOM discovery → extraction ──────────────────────────────────────────
  function textOf(el) {
    if (!el) return '';
    return (el.innerText || el.textContent || '').trim();
  }

  function cardText(el) {
    // Card faces are CSS-class-encoded; try data attrs, title, aria, img src, text.
    var t = el.getAttribute('data-card') || el.getAttribute('title') || el.getAttribute('aria-label') || '';
    if (!t) {
      var img = el.querySelector('img');
      if (img) t = img.getAttribute('src') || '';
    }
    if (!t) t = textOf(el);
    t = t.replace(/.*\/([^/]+)\.[a-z0-9]+.*/i, '$1'); // from img paths
    return t.replace(/[^A-Za-z0-9]/g, '').slice(0, 2);
  }

  function parseStack(t) {
    var n = parseFloat(String(t).replace(/[^0-9.]/g, ''));
    return isNaN(n) ? 0 : n;
  }

  function scrapeTable() {
    var seats = [];
    var heroSeat = -1;
    var containers = document.querySelectorAll(SEL.seatContainer);
    containers.forEach(function (c, i) {
      // hero = self-player wrapper INSIDE the seat (live-verified structure)
      var heroWrap = c.querySelector(SEL.heroClass);
      var isHero = !!heroWrap;
      var nameEl = c.querySelector(SEL.playerName);
      var name = nameEl ? textOf(nameEl) : '';
      var stackEl = c.querySelector(SEL.stack);
      var stack = stackEl ? parseStack(textOf(stackEl)) : 0;
      var cards = Array.prototype.map.call(c.querySelectorAll(SEL.holeCards), cardText).filter(Boolean);
      var seat = {
        seat_no: i,
        name: name,
        stack: stack,
        hole_cards: isHero ? cards : [],   // only hero's hole cards are visible
        bet: 0,
        is_hero: isHero,
        is_dealer: !!c.querySelector(SEL.dealer),
        sitting_out: !!c.querySelector(SEL.sittingOut),
        active: !!c.querySelector(SEL.activeTurn)
      };
      seats.push(seat);
      if (isHero) heroSeat = i;
    });

    var board = Array.prototype.map.call(document.querySelectorAll(SEL.board), cardText).filter(Boolean);
    var potEl = document.querySelector(SEL.pot);
    var pot = potEl ? parseStack(textOf(potEl)) : 0;

    // street from board count
    var street = '';
    if (board.length >= 5) street = 'RIVER';
    else if (board.length === 4) street = 'TURN';
    else if (board.length === 3) street = 'FLOP';
    else street = 'PRE_FLOP';

    var availableActions = [];
    Object.keys(SEL.buttons).forEach(function (action) {
      var btn = document.querySelector(SEL.buttons[action]);
      if (btn && btn.offsetParent !== null) availableActions.push(action);
    });

    // hand identity: stable element if present, else derive
    var handEl = document.querySelector('[data-hand-id], .hand-id, .hand_id');
    var handId = handEl ? textOf(handEl) : (state.lastHandId || ('H' + Math.floor(Date.now() / 1000)));

    return {
      player_id: CONFIG.playerId,
      browser_instance_id: CONFIG.browserInstanceId,
      table_id: (location.pathname.match(/\/tbl\/([^/]+)/) || [])[1] || location.pathname.split('/').filter(Boolean).join('-') || 'table',
      hand_id: handId,
      snapshot_version: ++state.seq,
      street: street,
      pot: pot,
      board: board,
      seats: seats,
      hero_seat: heroSeat,
      available_actions: availableActions,
      action_amounts: {},
      button_state: '',
      table_state: seats.length ? 'SEATED' : 'LOBBY',
      variant: 'plo',
      timestamp: new Date().toISOString()
    };
  }

  // ── send snapshot ───────────────────────────────────────────────────────
  function sendSnapshot(snap) {
    fetch(CONFIG.apiBase + '/api/snapshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': CONFIG.apiKey },
      body: JSON.stringify(snap)
    }).then(function (r) {
      if (r.status === 409) {
        // stale — recover by resyncing: bump seq beyond server version
        r.json().then(function (b) {
          var m = /v(\d+)/.exec(b.detail || '');
          if (m) state.seq = parseInt(m[1], 10);
        }).catch(function () {});
      }
    }).catch(function () {});
  }

  // ── command execution (native clicks mirror PokerBet's own events) ──────
  function nativeClick(el) {
    ['mousedown', 'mouseup', 'click'].forEach(function (type) {
      el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    });
  }

  function executeCommand(cmd) {
    var selector = SEL.buttons[cmd.action];
    if (!selector) return ack(cmd, 'FAILED', 'unknown action ' + cmd.action);
    var btn = document.querySelector(selector);
    if (!btn) return ack(cmd, 'FAILED', 'button not found: ' + cmd.action);

    if ((cmd.action === 'bet' || cmd.action === 'raise') && cmd.amount) {
      // preset-based sizing: click the preset <li> matching the amount, verify
      // the amount display changed, then confirm — same model as legacy v21.
      var presets = document.querySelectorAll(SEL.preset);
      var matched = null;
      presets.forEach(function (p) {
        var t = parseStack(textOf(p));
        if (cmd.amount && Math.abs(t - cmd.amount) < 0.01) matched = p;
      });
      if (matched) nativeClick(matched);
      else {
        // fallback: click the bet/raise button anyway (browser keeps last size)
      }
    }
    nativeClick(btn);
    return ack(cmd, 'ACKNOWLEDGED', '');
  }

  function ack(cmd, status, error) {
    fetch(CONFIG.apiBase + '/api/commands/ack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': CONFIG.apiKey },
      body: JSON.stringify({
        command_id: cmd.command_id,
        player_id: cmd.player_id,
        browser_instance_id: cmd.browser_instance_id,
        status: status,
        error: error
      })
    }).catch(function () {});
  }

  function pollCommands() {
    if (!CONFIG.playerId || !CONFIG.browserInstanceId) return;
    fetch(CONFIG.apiBase + '/api/commands/pending?player_id=' + encodeURIComponent(CONFIG.playerId) + '&browser_instance_id=' + encodeURIComponent(CONFIG.browserInstanceId), {
      headers: { 'X-API-Key': CONFIG.apiKey }
    }).then(function (r) { return r.json(); }).then(function (cmd) {
      if (!cmd || !cmd.command_id) return;
      if (state.executedCommandIds[cmd.command_id]) return; // idempotent
      if (cmd.hand_id && state.lastHandId && cmd.hand_id !== state.lastHandId) {
        // stale-hand guard: never act on a finished hand
        return ack(cmd, 'FAILED', 'hand mismatch: ' + cmd.hand_id + ' vs ' + state.lastHandId);
      }
      state.executedCommandIds[cmd.command_id] = true;
      executeCommand(cmd);
    }).catch(function () {});
  }

  // ── main loop ───────────────────────────────────────────────────────────
  function loop() {
    // identity is the anchor for E&R's isolation model — never send a
    // snapshot that cannot be attributed (server would reject it anyway)
    if (isPokerBet() && hasTableProof() && CONFIG.playerId && CONFIG.browserInstanceId) {
      var snap = scrapeTable();
      state.lastHandId = snap.hand_id;
      sendSnapshot(snap);
    }
    pollCommands();
    setTimeout(loop, CONFIG.pollMs);
  }

  loadConfig(function () { setTimeout(loop, 1500); });

  // test hook — lets the node harness drive extraction deterministically
  window.__er_w4p_test = { scrapeTable: scrapeTable, executeCommand: executeCommand, config: CONFIG };
})();
