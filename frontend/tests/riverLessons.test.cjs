const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const read=file=>fs.readFileSync(path.join(__dirname,'..',file),'utf8');
const compile=source=>ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
function helpers(fetch=()=>{throw Error('Unexpected network')}) {
 const scope={exports:{},process:{env:{}},fetch,DOMException,AbortController,setTimeout,clearTimeout,require:()=>({ensureProfile:async()=>({token:'test-profile'})})};
 vm.runInNewContext(compile(read('services/riverLessons.ts')),scope);return scope.exports;
}
function nodes(tree,predicate) {
 if(!tree||typeof tree!=='object')return[];
 if(Array.isArray(tree))return tree.flatMap(item=>nodes(item,predicate));
 return [...(predicate(tree)?[tree]:[]),...nodes(tree.props?.children,predicate)];
}
function text(tree) {
 if(tree==null)return'';if(typeof tree!=='object')return String(tree);
 if(Array.isArray(tree))return tree.map(text).join('');return text(tree.props?.children);
}
function fixture(id,opponents=1) {
 return {id,opponents,board:['2c','4d','7h','9s','Jc'],own_hand:'AhAd',actor_id:'a',button_id:'b',pot:20,small_blind:5,big_blind:10,
  actions:['CHECK','BET 10','BET 20'],tree:{bet_sizes:[10,20],raise_sizes:[],max_raises:0},players:[{id:'a',seat:0,stack:990,total_committed:10,range:[{cards:'AhAd',weight:1}]}]};
}
function result(ticket,id,status='ready') {
 return {ticket_id:ticket,lesson_id:id,version:'v1',state:'completed',result:{status,reasons:status==='ready'?[]:[{code:'QUALITY_GATE_FAILED'}],
  quality:{passed:status==='ready',value:status==='ready'?.1:1,gate:.5},admission:{offline_analysis_allowed:status==='ready',live_advice_allowed:false},
  action_values:{version:'fixed_policy_decision_ev_v1',actor_id:'a',own_hand:'AhAd',actions:['CHECK','BET 10','BET 20'],ev_chips:[5,10,7],gap_to_best_chips:[5,0,3],policy_ev_chips:6.9,sunk_chips:10,baseline:'current_decision',continuation:'fixed_learned_policy'},
  candidate:{own_hand:'AhAd',actions:['CHECK','BET 10','BET 20'],probabilities:[.5,.3,.2]}}};
}
function page(enabled=true) {
 const slots=[],effects=[];let cursor=0;
 const calls={submit:[],poll:[],cancel:[]};
 const catalog={enabled,version:'v1',lessons:enabled?[fixture('river-1'),fixture('river-2',2)]:[]};
 const api={catalog:async()=>catalog,submit:(id,version,signal)=>{const d=deferred();calls.submit.push({id,version,signal,...d});return d.promise;},
  poll:(ticket,signal)=>{const d=deferred();calls.poll.push({ticket,signal,...d});return d.promise;},cancel:async ticket=>{calls.cancel.push(ticket);return{state:'cancelled'};}};
 const react={useState:initial=>{const i=cursor++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},
  useRef:initial=>{const i=cursor++;if(!(i in slots))slots[i]={current:initial};return slots[i];},
  useEffect:(fn,deps)=>{const i=cursor++;if(!(i in slots)||!deps.every((d,j)=>d===slots[i]?.deps[j])){slots[i]?.cleanup?.();slots[i]={deps};effects.push(()=>{slots[i].cleanup=fn();});}}};
 const jsx=(type,props)=>({type,props});const h=helpers();
 const scope={exports:{},AbortController,Error,require:name=>name==='react'?react:name==='react/jsx-runtime'?{jsx,jsxs:jsx}:name.includes('LanguageProvider')?{useI18n:()=>({t:x=>x})}:name.includes('riverLessons')?{...h,RiverLessonsApi:api}:{default:name}};
 vm.runInNewContext(compile(read('app/practice/river/page.tsx')),scope);
 const render=()=>{cursor=0;const tree=scope.exports.default();while(effects.length)effects.shift()();return tree;};
 return {calls,render,async load(){render();await tick();return render();},button(tree){return nodes(tree,n=>n.type==='button'&&text(n).includes('Calculate model'))[0];}};
}

test('the real page blocks duplicate starts and only displays admitted action frequencies',async()=>{
 const p=page();let tree=await p.load();const start=p.button(tree);start.props.onClick();start.props.onClick();assert.equal(p.calls.submit.length,1);
 p.calls.submit[0].resolve({ticket_id:'one'});await tick();assert.equal(p.calls.poll.length,1);
 p.calls.poll[0].resolve(result('one','river-1'));await tick();tree=p.render();assert.equal(nodes(tree,n=>n.props?.className==='river-frequency').length,3);assert.match(text(tree),/50.0%/);
});
test('changing the example cancels the old ticket and ignores a late successful poll',async()=>{
 const p=page();p.button(await p.load()).props.onClick();p.calls.submit[0].resolve({ticket_id:'old'});await tick();
 let tree=p.render();nodes(tree,n=>n.type==='select')[0].props.onChange({target:{value:'river-2'}});assert.ok(p.calls.cancel.includes('old'));assert.equal(p.calls.poll[0].signal.aborted,true);
 p.calls.poll[0].resolve(result('old','river-1'));await tick();tree=p.render();assert.equal(nodes(tree,n=>n.props?.className==='river-frequency').length,0);
 p.button(tree).props.onClick();p.calls.submit[1].resolve({ticket_id:'new'});await tick();p.calls.poll[1].resolve(result('new','river-2'));await tick();
 assert.equal(nodes(p.render(),n=>n.props?.className==='river-frequency').length,3);
});
test('a late submit after cancellation is cancelled before polling',async()=>{
 const p=page();p.button(await p.load()).props.onClick();let tree=p.render();nodes(tree,n=>n.type==='select')[0].props.onChange({target:{value:'river-2'}});
 p.calls.submit[0].resolve({ticket_id:'late'});await tick();assert.ok(p.calls.cancel.includes('late'));assert.equal(p.calls.poll.length,0);
});
test('refused quality cannot expose an attached candidate and a disabled engine has no calculate button',async()=>{
 const p=page();p.button(await p.load()).props.onClick();p.calls.submit[0].resolve({ticket_id:'bad'});await tick();p.calls.poll[0].resolve(result('bad','river-1','quality_rejected'));await tick();
 const tree=p.render();assert.equal(nodes(tree,n=>n.props?.className==='river-frequency').length,0);assert.match(text(tree),/did not pass the quality check/);
 const off=page(false);assert.equal(off.button(await off.load()),undefined);assert.match(text(off.render()),/not connected/);
});
test('API calls keep catalog public and jobs authenticated, abort before submit, and sanitize errors',async()=>{
 const calls=[];const h=helpers(async(url,options)=>{calls.push({url,options});return{ok:true,json:async()=>({})};});
 await h.RiverLessonsApi.catalog();await h.RiverLessonsApi.submit('river-1','v1');assert.equal(calls[0].options.headers.Authorization,undefined);assert.equal(calls[1].options.headers.Authorization,'Bearer test-profile');assert.equal(calls[1].options.cache,'no-store');
 const abort=new AbortController();abort.abort();await assert.rejects(h.RiverLessonsApi.submit('river-1','v1',abort.signal),/Aborted/);assert.equal(calls.length,2);
 assert.doesNotMatch(h.lessonError('/private/server/trace'),/private|trace/);assert.equal(h.lessonResultMatches({lesson_id:'a',version:'1'},'a','2'),false);
});

test('EV comparison shows values, fixed continuation and the correct baseline only for valid results',async()=>{
 const p=page();p.button(await p.load()).props.onClick();p.calls.submit[0].resolve({ticket_id:'ev'});await tick();p.calls.poll[0].resolve(result('ev','river-1'));await tick();
 const output=text(p.render());assert.match(output,/Compare actions/);assert.match(output,/\+10.00/);assert.match(output,/\+6.90/);
 assert.match(output,/Earlier contributions are already spent/);assert.match(output,/same calculated strategy/);assert.match(output,/Best in this comparison/);
 const h=helpers(),lesson=fixture('river-1'),valid=result('ev','river-1').result;
 assert.ok(h.lessonActionValues(valid,lesson));
 for(const change of [r=>r.action_values.ev_chips[0]=NaN,r=>r.action_values.gap_to_best_chips[0]=4,
  r=>r.action_values.actor_id='other',r=>r.action_values.own_hand='KhKd',r=>r.action_values.continuation='best_response',
  r=>r.action_values.policy_ev_chips=99,r=>r.status='quality_rejected',r=>r.admission.live_advice_allowed=true,
  r=>r.candidate.probabilities=[NaN,.3,.2],r=>delete r.action_values]) {
  const invalid=structuredClone(valid);change(invalid);assert.equal(h.lessonActionValues(invalid,lesson),null);
 }
});
test('an older result keeps frequencies and asks for a new calculation instead of fabricating EV',async()=>{
 const p=page();p.button(await p.load()).props.onClick();p.calls.submit[0].resolve({ticket_id:'legacy'});await tick();
 const legacy=result('legacy','river-1');delete legacy.result.action_values;p.calls.poll[0].resolve(legacy);await tick();
 const tree=p.render();assert.equal(nodes(tree,n=>n.props?.className==='river-frequency').length,3);assert.match(text(tree),/Action EV is unavailable/);assert.doesNotMatch(text(tree),/EV of the mixed strategy/);
});
