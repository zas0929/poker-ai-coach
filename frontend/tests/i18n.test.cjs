const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = path.join(__dirname, '../i18n/translate.ts');
const code = ts.transpileModule(fs.readFileSync(source, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true } }).outputText;
const context = { exports: {}, require: name => require(path.join(path.dirname(source), name)) };
vm.runInNewContext(code, context);
const { translate, displayPlayer } = context.exports;

for (const locale of ['ru', 'uk']) {
  const t = value => translate(value, locale);
  test(`${locale}: advice saved in English and nested action labels`, () => {
    const advice = 'Matches the coach heuristic. Fold is preferred with J8o because your equity is below the price being offered. Calling is estimated at -12.5 EV.';
    const actual = t(advice);
    assert.match(actual, /J8o/); assert.match(actual, /-12\.5/);
    assert.doesNotMatch(actual, /Matches|Fold|Calling|preferred/);
    const summary = t('Checking is reasonable. AKo is a strong, but your high card plus gutshot straight draw does not have enough estimated equity to force value.');
    assert.doesNotMatch(summary, /Checking|strong|high card|gutshot|enough/);
    assert.match(summary, /AKo/);
  });
  test(`${locale}: grading explanations preserve exact math`, () => {
    const math = '20 / (40 + 20) = 33.3%. Exclude 80 uncallable chips returned to the opponent. This call price assumes no further betting or rake.';
    assert.match(t(math), /20 \/ \(40 \+ 20\) = 33\.3%/);
    assert.doesNotMatch(t(math), /Exclude|uncallable|assumes/);
    const actions = t('Allowed actions: fold, call, raise. Check requires no outstanding call. Bet opens an unbet street; raise needs another funded opponent, available chips and reopened raise rights.');
    assert.doesNotMatch(actions, /Allowed|fold|call|raise|Check|Bet/);
  });
  test(`${locale}: names, IDs and nontext React children are preserved`, () => {
    for (const name of ['Call', 'You', 'Ready', 'Роман', 'Олена']) assert.equal(displayPlayer({ id: 'seat-123', name }, t), name);
    assert.equal(t(123), 123); assert.equal(t(null), null);
    const element = { type: 'span', props: { children: 'Call' } }; assert.equal(t(element), element);
    assert.equal(t('AKs'), 'AKs'); assert.equal(t('77900935'), '77900935');
    assert.notEqual(displayPlayer({ id: 'hero', name: 'You' }, t), 'You');
  });
}

test('every dictionary entry has both languages and matching interpolation slots', () => {
  const messages = require('../i18n/messages.json');
  const slots = text => [...text.matchAll(/\{\d+\}/g)].map(m => m[0]).sort();
  for (const [key, values] of Object.entries(messages)) {
    assert.ok(values.ru && values.uk, key);
    assert.deepEqual(slots(values.ru), slots(key), key);
    assert.deepEqual(slots(values.uk), slots(key), key);
  }
});

test('all explicitly translated UI literals exist in the catalog', () => {
  const messages = require('../i18n/messages.json');
  function walk(directory) {
    for (const file of fs.readdirSync(directory)) {
      const target = path.join(directory, file);
      if (fs.statSync(target).isDirectory()) { walk(target); continue; }
      if (!target.endsWith('.tsx')) continue;
      const source = ts.createSourceFile(target, fs.readFileSync(target, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      function visit(node) {
        if (ts.isCallExpression(node) && node.expression.getText(source) === 't' && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
          const key = node.arguments[0].text.trim();
          if (/[a-z]/i.test(key)) assert.ok(messages[key], `${target}: ${key}`);
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
  walk(path.join(__dirname, '../app'));
  walk(path.join(__dirname, '../components'));
});
