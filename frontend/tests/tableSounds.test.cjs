const { test } = require('node:test');
const assert = require('node:assert/strict');
const ts = require('typescript');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../services/tableSounds.ts'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const sandbox = { exports: {} }; vm.runInNewContext(code, sandbox);
const { newActionSounds } = sandbox.exports;
const hand = history => ({ hand_id: 'one', history: history.map(action => ({ action })) });
test('sounds follow only new checks and chip actions, including batched bot turns', () => {
  assert.deepEqual(Array.from(newActionSounds(hand(['small_blind']), hand(['small_blind','call','check','bet','raise','fold']))), ['chips','check','chips','chips']);
});
test('snapshots, reconnects, replay and new hands do not replay prior actions', () => {
  const state = hand(['check', 'bet']);
  for (const previous of [null, state, hand(['check','bet','call']), { ...state, hand_id: 'old' }]) assert.equal(newActionSounds(previous, state).length, 0);
});
