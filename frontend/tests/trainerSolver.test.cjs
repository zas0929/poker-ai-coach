const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), ts = require('typescript');
const fixture = require('./fixtures/trainer-river.json');
const copy = value => JSON.parse(JSON.stringify(value));
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;});return {promise,resolve,reject}; };
const tick = () => new Promise(setImmediate);
function load() {
 const scope = {exports:{},AbortController,DOMException,Error,process:{env:{}},setTimeout,clearTimeout,require:()=>({ensureProfile:async()=>({token:'test'})})};
 const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../services/trainerSolver.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
 vm.runInNewContext(code,scope);return scope.exports;
}
function harness() {
 const updates=[], starts=[], polls=[], cancellations=[], waits=[];
 const api={submit:(position,nonce,signal)=>{const d=deferred();starts.push({position,nonce,signal,...d});return d.promise;},
  poll:(ticket,signal)=>{const d=deferred();polls.push({ticket,signal,...d});return d.promise;},cancel:async ticket=>{cancellations.push(ticket);return {state:'cancelled'};}};
 const Controller=load().CurrentTrainerSolver;
 const runner=new Controller(v=>updates.push(v),api,()=>{const d=deferred();waits.push(d);return d.promise;},()=>String(starts.length));
 return {updates,starts,polls,cancellations,waits,runner};
}
const pending = ticket => ({...copy(fixture.result),ticket_id:ticket,state:'running',actions:null,quality:null});
test('browser position identity exactly matches Python and excludes opponent cards',()=>{
 const h=load();assert.equal(h.trainerPosition(fixture.hand),fixture.position);
 const changed=copy(fixture.hand);changed.players[1].cards=[{rank:'A',suit:'spades'}];
 assert.equal(h.trainerPosition(changed),fixture.position);
 changed.players[0].stack++;assert.notEqual(h.trainerPosition(changed),fixture.position);
});
test('only current, finite, legal and quality-approved model actions can render',()=>{
 const h=load();assert.ok(h.currentModelActions(fixture.result,fixture.hand));
 for(const change of [r=>r.actions[0].ev_chips=NaN,r=>r.quality.value=2,r=>r.model.own_hand='AsKs',r=>r.actions[0].action='BET 999999',r=>r.client_position='old']){
  const bad=copy(fixture.result);change(bad);assert.equal(h.currentModelActions(bad,fixture.hand),null);
 }
 const hand=copy(fixture.hand);hand.players[0].stack++;assert.equal(h.currentModelActions(fixture.result,hand),null);
});
test('a late submit releases only its own lease and cannot publish after cancellation',async()=>{
 const h=harness();const p=h.runner.request(fixture.hand);h.runner.cancel();
 h.starts[0].resolve(pending('late'));await p;
 assert.deepEqual(h.cancellations,['late']);assert.equal(h.updates.at(-1),null);assert.equal(h.polls.length,0);
});
test('background polling shows values only for matching decision and clears immediately on action',async()=>{
 const h=harness();const p=h.runner.request(fixture.hand);h.starts[0].resolve(pending('current'));await tick();
 assert.equal(h.updates.at(-1).state,'running');h.waits[0].resolve();await tick();
 h.polls[0].resolve({...copy(fixture.result),ticket_id:'current'});await p;
 assert.equal(h.updates.at(-1).state,'ready');assert.equal(h.updates.at(-1).actions.length,fixture.result.actions.length);
 h.runner.cancel();assert.equal(h.updates.at(-1),null);assert.ok(h.cancellations.includes('current'));
});
test('late polling cannot overwrite a newer decision or show an old error',async()=>{
 const h=harness();const p=h.runner.request(fixture.hand);h.starts[0].resolve(pending('old'));await tick();h.waits[0].resolve();await tick();
 const newer=copy(fixture.hand);newer.hand_id='new';const next=h.runner.request(newer);
 h.polls[0].resolve({...copy(fixture.result),ticket_id:'old'});await p;
 assert.equal(h.updates.at(-1).state,'preparing');
 h.starts[1].resolve({state:'disabled',ticket_id:null});await next;assert.equal(h.updates.at(-1).state,'disabled');
});
test('mismatched server identity and failed calculations leave the usual coach alone',async()=>{
 const h=harness();const p=h.runner.request(fixture.hand);h.starts[0].resolve({...copy(fixture.result),hand_id:'other'});await p;
 assert.equal(h.updates.at(-1).state,'unavailable');
 const next=h.runner.request(fixture.hand);h.starts[1].reject(new Error('timeout'));await next;assert.equal(h.updates.at(-1).state,'unavailable');
});
test('no solver request runs for another street or another acting player',async()=>{
 const h=harness();await h.runner.request({...fixture.hand,street:'flop'});await h.runner.request({...fixture.hand,current_player_id:'villain'});
 assert.equal(h.starts.length,0);assert.equal(h.updates.at(-1),null);
});
test('actual coach supplement renders sizes, EV, coverage and busy state without action controls',()=>{
 const h=load(),jsx=(type,props)=>({type,props});
 const scope={exports:{},require:name=>name==='react/jsx-runtime'?{jsx,jsxs:jsx}:name.includes('LanguageProvider')?{useI18n:()=>({t:v=>v})}:h};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../components/TrainerSolverPanel.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,scope);
 function text(tree){if(tree==null)return '';if(typeof tree!=='object')return String(tree);if(Array.isArray(tree))return tree.map(text).join('');return text(tree.props?.children);}
 const content=text(scope.exports.default({result:fixture.result,hand:fixture.hand}));
 assert.match(content,/EV/);assert.match(content,/range coverage/);assert.match(content,/Frequency/);assert.match(content,/bet \d+/);
 const busy=text(scope.exports.default({result:pending('one'),hand:fixture.hand}));assert.match(busy,/You can act/);assert.doesNotMatch(busy,/Frequency/);
});

const turnFixture = require('./fixtures/trainer-turn.json');
test('turn calculation uses its own contract and cannot render a river result', async()=>{
 const api=load();assert.equal(api.trainerPosition(turnFixture.hand),turnFixture.position);
 assert.ok(api.currentModelActions(turnFixture.result,turnFixture.hand));
 for(const change of [r=>r.contract_version='trainer_current_river_v1',r=>r.model.board.push('As'),r=>r.client_position='old-turn',r=>r.actions[0].gap_chips=10000]){
  const bad=copy(turnFixture.result);change(bad);assert.equal(api.currentModelActions(bad,turnFixture.hand),null);
 }
 const h=harness();const pending=h.runner.request(turnFixture.hand);
 h.starts[0].resolve({...copy(turnFixture.result),ticket_id:'turn-job',state:'running',actions:null,quality:null});await tick();
 assert.equal(h.updates.at(-1).state,'running');h.waits[0].resolve();await tick();
 h.polls[0].resolve({...copy(turnFixture.result),ticket_id:'turn-job'});await pending;
 assert.equal(h.updates.at(-1).state,'ready');
 h.runner.cancel();assert.equal(h.updates.at(-1),null);assert.ok(h.cancellations.includes('turn-job'));
});
test('a river response to a turn request is unavailable and cannot replace action buttons',async()=>{
 const h=harness();const pending=h.runner.request(turnFixture.hand);
 h.starts[0].resolve({...copy(turnFixture.result),contract_version:'trainer_current_river_v1'});await pending;
 assert.equal(h.updates.at(-1).state,'unavailable');assert.equal(h.updates.at(-1).reason,'CURRENT_TURN_UNAVAILABLE');
});
test('turn panel shows future river scope, per-street raise caps and sizes',()=>{
 const h=load(),jsx=(type,props)=>({type,props});
 const scope={exports:{},require:name=>name==='react/jsx-runtime'?{jsx,jsxs:jsx}:name.includes('LanguageProvider')?{useI18n:()=>({t:v=>v})}:h};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../components/TrainerSolverPanel.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,scope);
 function text(tree){if(tree==null)return '';if(typeof tree!=='object')return String(tree);if(Array.isArray(tree))return tree.map(text).join('');return text(tree.props?.children);}
 const content=text(scope.exports.default({result:turnFixture.result,hand:turnFixture.hand}));
 assert.match(content,/Current turn model/);assert.match(content,/All compatible river cards/);
 assert.match(content,/turn 1, river 0/);assert.match(content,/Model sizes/);assert.match(content,/EV/);
 const refused=text(scope.exports.default({result:{...copy(turnFixture.result),state:'unavailable',actions:null,quality:null,reason:'MODEL_BUDGET_EXCEEDED'},hand:turnFixture.hand}));
 assert.match(refused,/tree budget/);assert.doesNotMatch(refused,/Frequency/);
});

test('panel separates numerical convergence from advice reliability and flags disagreement',()=>{
 const h=load(), jsx=(type,props)=>({type,props});
 const scope={exports:{},require:name=>name==='react/jsx-runtime'?{jsx,jsxs:jsx}:name.includes('LanguageProvider')?{useI18n:()=>({t:v=>v})}:h};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../components/TrainerSolverPanel.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,scope);
 function text(tree){if(tree==null)return '';if(typeof tree!=='object')return String(tree);if(Array.isArray(tree))return tree.map(text).join('');return text(tree.props?.children);}
 const result=copy(turnFixture.result), hand=turnFixture.hand;
 const best=result.actions.reduce((a,b)=>a.ev_chips>b.ev_chips?a:b).action.split(' ')[0].toLowerCase();
 const advice={hand_id:hand.hand_id,street:hand.street,pot:hand.pot,recommended_action:best==='check'?'fold':'check'};
 const content=text(scope.exports.default({result,hand,analysis:advice}));
 assert.match(content,/reliability has not been established/);
 assert.match(content,/100% is not a win probability/);
 assert.match(content,/does not measure full-range advice accuracy/);
 assert.match(content,/model and heuristic coach disagree/);
 const same=text(scope.exports.default({result,hand,analysis:{...advice,recommended_action:best}}));
 assert.doesNotMatch(same,/model and heuristic coach disagree/);
 const stale=text(scope.exports.default({result,hand,analysis:{...advice,hand_id:'old'}}));
 assert.doesNotMatch(stale,/model and heuristic coach disagree/);
});
