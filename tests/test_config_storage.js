/* E&R PokerBet — configuration wiring tests.
 * Run: node tests/test_config_storage.js
 * Verifies the options-page → chrome.storage → w4p.js path (per-device
 * configuration without editing JS) plus the fallback chain:
 *   window.ER_* globals > chrome.storage.local > dev defaults.
 */
'use strict';

const assert = require('assert');

// ── stubbed browser env with a mock chrome.storage ───────────────────────
let storageValues = {};
let onChangedHandler = null;

global.window = global;
global.location = {
  hostname: 'poker-web.pokerbet.co.za',
  pathname: '/18751019/tbl/2589954',
  href: 'https://poker-web.pokerbet.co.za/18751019/tbl/2589954'
};
global.fetch = () => Promise.resolve({ status: 200, json: () => Promise.resolve({}) });
global.MouseEvent = class { constructor(type, init) { this.type = type; this.init = init; } };
global.document = { querySelector: () => null, querySelectorAll: () => [] };
global.chrome = {
  storage: {
    local: { get: (keys, cb) => cb(storageValues) },
    onChanged: { addListener: (fn) => { onChangedHandler = fn; } }
  }
};

function freshLoad() {
  delete require.cache[require.resolve('../extension/w4p.js')];
  delete global.__er_w4p_loaded;
  require('../extension/w4p.js');
  return window.__er_w4p_test;
}

let passed = 0;
function test(name, fn) {
  try { fn(); console.log('  ✓ ' + name); passed++; }
  catch (e) { console.error('  ✗ ' + name + '\n    ' + e.message); process.exitCode = 1; }
}

// 1. storage wins when no window globals are set (the player-device case)
['ER_API_BASE', 'ER_API_KEY', 'ER_PLAYER_ID', 'ER_BROWSER_ID'].forEach(k => delete global[k]);
storageValues = {
  erApiBase: 'https://er.example.com',
  erApiKey: 'sekret',
  erPlayerId: 'PLAYER-001',
  erBrowserId: 'PLAYER-001-CHROME-01'
};
let s = freshLoad();
test('storage config applied when no window globals', () => {
  assert.strictEqual(s.config.apiBase, 'https://er.example.com');
  assert.strictEqual(s.config.apiKey, 'sekret');
  assert.strictEqual(s.config.playerId, 'PLAYER-001');
  assert.strictEqual(s.config.browserInstanceId, 'PLAYER-001-CHROME-01');
});

// 2. window globals take precedence (console-paste dev mode), storage fills gaps
global.ER_API_BASE = 'http://10.0.0.5:8090';
global.ER_PLAYER_ID = 'GLOBAL-PLAYER';
storageValues = { erBrowserId: 'STORED-BROWSER' };
s = freshLoad();
test('window globals override storage, storage fills gaps', () => {
  assert.strictEqual(s.config.apiBase, 'http://10.0.0.5:8090');
  assert.strictEqual(s.config.playerId, 'GLOBAL-PLAYER');
  assert.strictEqual(s.config.browserInstanceId, 'STORED-BROWSER');
  assert.strictEqual(s.config.apiKey, ''); // neither global nor storage → default
});

// 3. dev defaults when nothing is configured
['ER_API_BASE', 'ER_API_KEY', 'ER_PLAYER_ID', 'ER_BROWSER_ID'].forEach(k => delete global[k]);
storageValues = {};
s = freshLoad();
test('dev defaults when nothing configured', () => {
  assert.strictEqual(s.config.apiBase, 'http://127.0.0.1:8090');
  assert.strictEqual(s.config.playerId, '');
  assert.strictEqual(s.config.browserInstanceId, '');
});

// 4. saving the options page live-reloads the content script
storageValues = { erApiBase: 'https://er.example.com' };
s = freshLoad();
onChangedHandler({ erApiBase: { newValue: 'https://er2.example.com' } }, 'local');
test('storage.onChanged live-reloads config without tab reload', () => {
  assert.strictEqual(s.config.apiBase, 'https://er2.example.com');
});

console.log('\nconfig tests: ' + passed + ' passed');
process.exit(process.exitCode || 0);
