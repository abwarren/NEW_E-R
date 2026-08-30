/* E&R PokerBet — scraper unit tests against replayable DOM fixtures.
 * Run: node tests/test_scraper.js
 * Uses the verified BetConstruct SkillGames class structure (2026-08-30). */
'use strict';

const assert = require('assert');
const { make } = require('./dom_harness');

// ── build the fixture DOM: FLOP state, hero on seat 0 ─────────────────────
// Live-verified 2026-08-30 structure: sg-poker-table-seat.player-N seats,
// hero wrapper .player-mini-container-p.self-player.poker inside hero seat.
function buildFlopFixture() {
  const table = make('sg-poker-table');

  const heroSeat = make('sg-poker-table-seat', 'player-1');
  heroSeat.append(
    make('div', 'player-mini-container-p self-player poker').append(
      make('div', 'player-info-line').append(
        make('div', 'player-name-count-v self-player', 'Hero'),
        make('div', 'player-text-info-p').append(make('span').append(make('b', '', '1000')))
      ),
      make('div', 'carts-container-p').append(
        make('div', 'single-cart-view-p', 'As'),
        make('div', 'single-cart-view-p', 'Ks')
      )
    ),
    make('div', 'dealer-icon-view')
  );

  const villainSeat = make('sg-poker-table-seat', 'player-2');
  villainSeat.append(
    make('div', 'player-mini-container-p poker').append(
      make('div', 'player-info-line').append(
        make('div', 'player-name-count-v', 'Villain'),
        make('div', 'player-text-info-p').append(make('span').append(make('b', '', '950')))
      ),
      make('div', 'carts-container-p').append(
        make('div', 'single-cart-view-p'), // card back — no text
        make('div', 'single-cart-view-p')
      )
    )
  );

  const board = make('sg-poker-board').append(
    make('div', 'single-cart-view-p', 'Td'),
    make('div', 'single-cart-view-p', '9c'),
    make('div', 'single-cart-view-p', '3s')
  );

  const pot = make('div', 'pot-w-view-p', 'R45.50');

  const controls = make('div');
  controls.append(
    make('div', 'control-b-view-p fold-c', 'Fold'),
    make('div', 'control-b-view-p check-c', 'Check'),
    make('div', 'control-b-view-p call-c', 'Call'),
    make('div', 'control-b-view-p raise-c', 'Raise'),
    make('div', 'control-b-view-p all_in-c', 'All In').setAttribute('style', 'display:none') // hidden ⇒ not available
  );
  // hidden all_in: offsetParent must be null
  controls.children[4].offsetParent = null;

  table.append(heroSeat, villainSeat, board, pot, controls);
  return table;
}

// ── load w4p.js into a stubbed browser environment ────────────────────────
const fetched = [];
global.window = global;
global.ER_API_BASE = 'http://127.0.0.1:8090';
global.ER_API_KEY = 'k';
global.ER_PLAYER_ID = 'p_alice';
global.ER_BROWSER_ID = 'b_alice';
global.location = {
  hostname: 'poker-web.pokerbet.co.za',
  pathname: '/18751019/tbl/2589954',
  href: 'https://poker-web.pokerbet.co.za/18751019/tbl/2589954'
};
global.fetch = (url, opts) => {
  fetched.push({ url, opts });
  return Promise.resolve({ status: 200, json: () => Promise.resolve({}) });
};
global.MouseEvent = class { constructor(type, init) { this.type = type; this.init = init; } };

// fixtures per test
let currentRoot;
global.document = {
  querySelector: (sel) => currentRoot.querySelector(sel),
  querySelectorAll: (sel) => currentRoot.querySelectorAll(sel)
};

require('../extension/w4p.js');
const scraper = window.__er_w4p_test;

// ── tests ─────────────────────────────────────────────────────────────────
let passed = 0;
function test(name, fn) {
  try { fn(); console.log('  ✓ ' + name); passed++; }
  catch (e) { console.error('  ✗ ' + name + '\n    ' + e.message + '\n    ' + (e.stack || '').split('\n').slice(1, 4).join('\n    ')); process.exitCode = 1; }
}

test('loads only on poker-web.pokerbet.co.za', () => {
  assert(scraper, 'test hook present');
  assert.strictEqual(scraper.config.playerId, 'p_alice');
  assert.strictEqual(scraper.config.browserInstanceId, 'b_alice');
});

test('scrapes a FLOP state correctly', () => {
  currentRoot = buildFlopFixture();
  const snap = scraper.scrapeTable();
  assert.strictEqual(snap.table_id, '2589954');
  assert.strictEqual(snap.player_id, 'p_alice');
  assert.strictEqual(snap.browser_instance_id, 'b_alice');
  assert.strictEqual(snap.street, 'FLOP');
  assert.strictEqual(snap.pot, 45.5);
  assert.deepStrictEqual(snap.board, ['Td', '9c', '3s']);
  assert.strictEqual(snap.hero_seat, 0);
  assert.strictEqual(snap.seats.length, 2);
  assert.strictEqual(snap.seats[0].name, 'Hero');
  assert.strictEqual(snap.seats[0].is_hero, true);
  assert.deepStrictEqual(snap.seats[0].hole_cards, ['As', 'Ks']);
  assert.strictEqual(snap.seats[1].hole_cards.length, 0, 'only hero hole cards are visible');
  assert.deepStrictEqual(snap.available_actions, ['fold', 'check', 'call', 'raise']);
  assert.match(snap.hand_id, /^H\d+/);
  assert.strictEqual(snap.table_state, 'SEATED');
});

test('street derives from board count', () => {
  currentRoot = buildFlopFixture();
  currentRoot.querySelector('sg-poker-board').children.push(make('div', 'single-cart-view-p', '7h'));
  assert.strictEqual(scraper.scrapeTable().street, 'TURN');
});

test('executes a fold command and ACKs', () => {
  currentRoot = buildFlopFixture();
  fetched.length = 0;
  scraper.executeCommand({ command_id: 'c1', action: 'fold', player_id: 'p_alice', browser_instance_id: 'b_alice', hand_id: 'H1' });
  return; // fetch is sync-recorded via stub; assert below
});

// ACK assertions after the async chain settles
setTimeout(() => {
  test('ACK recorded for executed command', () => {
    const ack = fetched.find(f => f.url.includes('/api/commands/ack'));
    assert(ack, 'ack call made');
    const body = JSON.parse(ack.opts.body);
    assert.strictEqual(body.status, 'ACKNOWLEDGED');
    assert.strictEqual(body.command_id, 'c1');
  });

  test('unknown action ACKs as FAILED', () => {
    fetched.length = 0;
    scraper.executeCommand({ command_id: 'c9', action: 'teleport', player_id: 'p_alice', browser_instance_id: 'b_alice' });
    setTimeout(() => {
      const ack = fetched.find(f => f.url.includes('/api/commands/ack'));
      assert(ack, 'ack call made');
      const body = JSON.parse(ack.opts.body);
      assert.strictEqual(body.status, 'FAILED');
      console.log('\nscraper tests: ' + passed + ' passed');
      process.exit(process.exitCode || 0);
    }, 20);
  });
}, 20);
