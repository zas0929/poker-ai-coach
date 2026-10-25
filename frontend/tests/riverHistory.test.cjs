const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const read=f=>fs.readFileSync(path.join(__dirname,'..',f),'utf8');
const compile=s=>ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
function nodes(tree,p){if(!tree||typeof tree!=='object')return[];if(Array.isArray(tree))return tree.flatMap(n=>nodes(n,p));return[...(p(tree)?[tree]:[]),...nodes(tree.props?.children,p)];}
function text(t){if(t==null)return'';if(typeof t!=='object')return String(t);if(Array.isArray(t))return t.map(text).join('');return text(t.props?.children);}
function assessment(id=11){return{decision_id:id,hand_id:'hand-'+id,source_version:'source-'+id,version:'model-'+id,supported:true,reason:null,
 chosen_action:'check',chosen_amount:null,coverage:[{player_id:'hero',public_combos:1081,selected_combos:2,weight_share:.002}],
 model:{selected_hands:{hero:['AhAd','8h8d'],villain:['KhKd','QhQd']},bet_sizes:[10,20],raise_sizes:[],max_raises:0},
 lesson:{id:'decision-'+id,actor_id:'hero',own_hand:'AhAd',board:['2c','4d','7h','9s','Jc'],pot:20,small_blind:5,big_blind:10,
 actions:['CHECK','BET 10','BET 20'],players:[{id:'hero',total_committed:10,range:[{cards:'AhAd',weight:1}]}]}};}
function completed(id=11,status='ready'){return{ticket_id:'ticket-'+id,lesson_id:'decision-'+id,version:'model-'+id,state:'completed',result:{
 status,quality:{passed:status==='ready',value:.1,gate:.5},reasons:[],admission:{offline_analysis_allowed:status==='ready',live_advice_allowed:false},
 candidate:{own_hand:'AhAd',actions:['CHECK','BET 10','BET 20'],probabilities:[.5,.3,.2]},
 action_values:{version:'fixed_policy_decision_ev_v1',actor_id:'hero',own_hand:'AhAd',actions:['CHECK','BET 10','BET 20'],ev_chips:[5,10,7],gap_to_best_chips:[5,0,3],policy_ev_chips:6.9,sunk_chips:10,baseline:'current_decision',continuation:'fixed_learned_policy'}}};}
function page(empty=false){
 const slots=[],effects=[];let cursor=0;const calls={submit:[],poll:[],cancel:[]};
 const react={useState:v=>{const i=cursor++;if(!(i in slots))slots[i]=v;return[slots[i],x=>slots[i]=typeof x==='function'?x(slots[i]):x];},
 useRef:v=>{const i=cursor++;if(!(i in slots))slots[i]={current:v};return slots[i];},
 useEffect:(fn,deps)=>{const i=cursor++;if(!(i in slots)||!deps.every((d,j)=>d===slots[i]?.deps[j])){slots[i]?.cleanup?.();slots[i]={deps};effects.push(()=>slots[i].cleanup=fn());}}};
 const scope={exports:{},process:{env:{}},DOMException,AbortController,setTimeout,clearTimeout,require:()=>({ensureProfile:async()=>({token:'profile'})})};
 vm.runInNewContext(compile(read('services/riverLessons.ts')),scope);const helpers=scope.exports;
 const api={list:async()=>({items:empty?[]:[11,22].map(id=>({decision_id:id,hand_id:'hand-'+id,created_at:'2026-10-25T12:00:00Z',chosen_action:'check',amount:null})),next_cursor:null}),detail:async id=>assessment(id),
 submit:(id,version,model,signal)=>{const d=deferred();calls.submit.push({id,version,model,signal,...d});return d.promise;}};
 const jobs={poll:(ticket,signal)=>{const d=deferred();calls.poll.push({ticket,signal,...d});return d.promise;},cancel:async ticket=>calls.cancel.push(ticket)};
 const jsx=(type,props)=>({type,props});const pageScope={exports:{},AbortController,require:n=>n==='react'?react:n==='react/jsx-runtime'?{jsx,jsxs:jsx}:n.includes('LanguageProvider')?{useI18n:()=>({t:x=>x,locale:'en'})}:n.includes('riverLessons')?{...helpers,RiverHistoryApi:api,RiverLessonsApi:jobs}:{default:n}};
 vm.runInNewContext(compile(read('app/practice/river/history/page.tsx')),pageScope);
 const render=()=>{cursor=0;const tree=pageScope.exports.default();while(effects.length)effects.shift()();return tree;};
 const start=tree=>nodes(tree,n=>n.type==='button'&&text(n)==='Calculate selected model')[0];
 return{calls,render,start,async load(){render();await tick();render();await tick();return render();}};
}
test('saved review submits only explicit model settings, blocks double starts, and identifies the actual action',async()=>{
 const p=page();const tree=await p.load();p.start(tree).props.onClick();p.start(tree).props.onClick();assert.equal(p.calls.submit.length,1);
 assert.equal(p.calls.submit[0].version,'source-11');assert.equal(p.calls.submit[0].model.selected_hands.hero[0],'AhAd');assert.equal(p.calls.submit[0].model.snapshot,undefined);
 p.calls.submit[0].resolve({ticket_id:'ticket-11',lesson_id:'decision-11',version:'model-11',assessment:assessment()});await tick();p.calls.poll[0].resolve(completed());await tick();
 const output=p.render();assert.match(text(output),/EV of the mixed strategy/);assert.match(text(output),/6.90/);assert.equal(nodes(output,n=>n.props?.className==='river-chosen').length,1);
});
test('editing ranges cancels the job and suppresses its late EV result',async()=>{
 const p=page();p.start(await p.load()).props.onClick();p.calls.submit[0].resolve({ticket_id:'ticket-11',lesson_id:'decision-11',version:'model-11',assessment:assessment()});await tick();
 nodes(p.render(),n=>n.type==='input'&&n.props.value==='AhAd 8h8d')[0].props.onChange({target:{value:'AhAd 8c8s'}});
 assert.ok(p.calls.cancel.includes('ticket-11'));assert.equal(p.calls.poll[0].signal.aborted,true);
 p.calls.poll[0].resolve(completed());await tick();assert.doesNotMatch(text(p.render()),/EV of the mixed strategy/);assert.match(text(p.render()),/Settings changed/);
});
test('changing the decision cancels a late submit before polling or displaying the previous model',async()=>{
 const p=page();p.start(await p.load()).props.onClick();nodes(p.render(),n=>n.type==='select')[0].props.onChange({target:{value:'22'}});p.render();await tick();
 p.calls.submit[0].resolve({ticket_id:'late',assessment:assessment()});await tick();assert.ok(p.calls.cancel.includes('late'));assert.equal(p.calls.poll.length,0);assert.doesNotMatch(text(p.render()),/EV of the mixed strategy/);
});
test('preflight refusal does not poll; quality refusal never displays attached EV',async()=>{
 const p=page();p.start(await p.load()).props.onClick();p.calls.submit[0].resolve({ticket_id:null,assessment:{...assessment(),supported:false,reason:'HISTORY_OWN_HAND_REQUIRED'}});await tick();
 assert.equal(p.calls.poll.length,0);assert.match(text(p.render()),/must include your saved hand/);
 p.start(p.render()).props.onClick();p.calls.submit[1].resolve({ticket_id:'ticket-11',lesson_id:'decision-11',version:'model-11',assessment:assessment()});await tick();p.calls.poll[0].resolve(completed(11,'quality_rejected'));await tick();assert.doesNotMatch(text(p.render()),/EV of the mixed strategy/);
});
test('an empty archive explains completion requirements instead of offering a fabricated hand',async()=>{
 const p=page(true),tree=await p.load();assert.equal(p.start(tree),undefined);assert.match(text(tree),/Older decisions without completion evidence are not imported/);
});
test('history requests authenticate with the profile, bypass caches and send settings without a snapshot',async()=>{
 const calls=[];const scope={exports:{},process:{env:{}},DOMException,AbortController,setTimeout,clearTimeout,
  fetch:async(url,options)=>{calls.push({url,options});return{ok:true,json:async()=>({})};},require:()=>({ensureProfile:async()=>({token:'private-profile'})})};
 vm.runInNewContext(compile(read('services/riverLessons.ts')),scope);
 await scope.exports.RiverHistoryApi.list(22);await scope.exports.RiverHistoryApi.detail(11);await scope.exports.RiverHistoryApi.submit(11,'source-11',assessment().model);
 assert.equal(calls.length,3);for(const call of calls){assert.equal(call.options.headers.Authorization,'Bearer private-profile');assert.equal(call.options.cache,'no-store');}
 assert.match(calls[0].url,/history\?before=22$/);assert.equal(JSON.parse(calls[2].options.body).snapshot,undefined);
});
