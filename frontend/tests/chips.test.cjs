const assert = require('node:assert/strict');
const { test } = require('node:test');
const ts = require('typescript');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../services/chips.ts'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const sandbox = { exports: {} }; vm.runInNewContext(code, sandbox);
const { chipBreakdown, CHIP_VALUES } = sandbox.exports;

test('displayed denominations represent the exact stack including low chips', () => {
  for (const amount of [0, 1, 2, 5, 24, 25, 99, 100, 399, 400, 499, 598, 601, 995, 1000, 25000, 999999, 1000000]) {
    const piles = chipBreakdown(amount);
    assert.equal(piles.reduce((sum, pile) => sum + pile.value * pile.count, 0), amount);
    assert.ok(piles.every(pile => Number.isInteger(pile.count) && pile.count > 0));
  }
});
test('generated stacks conserve amounts throughout the supported buy-in range', () => {
  for (let amount = 0; amount <= 1000000; amount += 7919) {
    assert.equal(chipBreakdown(amount).reduce((sum, pile) => sum + pile.value * pile.count, 0), amount);
  }
});
test('denomination palette has unique values and covers single-chip units', () => {
  assert.equal(new Set(CHIP_VALUES.map(chip => chip.value)).size, CHIP_VALUES.length);
  assert.equal(CHIP_VALUES.at(-1).value, 1);
});
