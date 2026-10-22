const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../services/latestAnalysis.ts'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const context = { exports: {}, AbortController, Error };
vm.runInNewContext(code, context);
const { LatestAnalysis } = context.exports;
function harness() {
  const calls = [], results = [], loading = [], errors = [];
  const hints = new LatestAnalysis((hand, signal) => new Promise((resolve, reject) => calls.push({ hand, signal, resolve, reject })),
    value => results.push(value), value => loading.push(value), value => errors.push(value));
  return { hints, calls, results, loading, errors };
}

test('a late hint cannot replace the newer street or clear its loading state', async () => {
  const h = harness();
  const old = h.hints.request({ hand_id: 'same', street: 'flop' });
  const next = h.hints.request({ hand_id: 'same', street: 'turn' });
  assert.equal(h.calls[0].signal.aborted, true);
  h.calls[0].resolve({ street: 'flop' }); await old;
  assert.equal(h.loading.at(-1), true);
  assert.equal(h.results.filter(Boolean).length, 0);
  h.calls[1].resolve({ street: 'turn' }); await next;
  assert.equal(h.results.at(-1).street, 'turn');
  assert.equal(h.loading.at(-1), false);
});

test('playing before the hint is ready cancels stale results and errors', async () => {
  for (const failure of [false, true]) {
    const h = harness();
    const request = h.hints.request({ hand_id: 'previous' });
    h.hints.cancel();
    if (failure) h.calls[0].reject(new Error('Old request failed'));
    else h.calls[0].resolve({ hand_id: 'previous' });
    await request;
    assert.equal(h.calls[0].signal.aborted, true);
    assert.equal(h.results.at(-1), null);
    assert.equal(h.loading.at(-1), false);
    assert.equal(h.errors.length, 0);
  }
});

test('a current analysis error is visible and the next request can succeed', async () => {
  const h = harness();
  const failed = h.hints.request({ hand_id: 'current' });
  h.calls[0].reject(new Error('Unavailable')); await failed;
  assert.equal(h.errors[0], 'Unavailable');
  assert.equal(h.loading.at(-1), false);
  const retry = h.hints.request({ hand_id: 'current' });
  h.calls[1].resolve({ equity: 0.55 }); await retry;
  assert.equal(h.results.at(-1).equity, 0.55);
});
