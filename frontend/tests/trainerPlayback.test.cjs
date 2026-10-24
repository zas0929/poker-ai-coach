const {test}=require('node:test');
const assert=require('node:assert/strict');
const ts=require('typescript'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const scope={exports:{},setTimeout,clearTimeout};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../services/trainerPlayback.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,scope);
const play=scope.exports.playTrainerTurns;
const state=(actor,street='preflop')=>({current_player_id:actor,street});
const flush=()=>new Promise(setImmediate);
test('each consecutive bot is revealed only after its own 1–2 second thinking pause; hero gets no extra wait',async()=>{
 const visible=[],durations=[],releases=[];let calls=0;
 const initial=state('ai1'),second=state('ai2'),hero=state('hero');
 const pending=play(initial,{signal:new AbortController().signal,random:()=>calls===1?0:0.9999,aiAction:async(id)=>{calls++;assert.equal(id,calls===1?'ai1':'ai2');return calls===1?second:hero;},advance:()=>assert.fail('no street to advance'),onState:s=>visible.push(s),wait:ms=>{durations.push(ms);return new Promise(resolve=>releases.push(resolve));}});
 await flush();assert.equal(calls,1);assert.equal(visible.length,0);assert.equal(durations[0],1000);
 releases.shift()();await flush();assert.deepEqual(visible,[second]);assert.equal(calls,2);assert.equal(durations[1],2000);
 releases.shift()();assert.equal(await pending,hero);assert.deepEqual(visible,[second,hero]);
});
test('street transitions then continue pacing every bot and stop at showdown',async()=>{
 const shown=[],waits=[];const result={...state(null,'showdown'),result:{}};
 const settled=await play(state(null),{signal:new AbortController().signal,random:()=>.5,advance:async()=>state('ai3','flop'),aiAction:async()=>result,onState:s=>shown.push(s),wait:async ms=>{waits.push(ms);}});
 assert.equal(settled,result);assert.equal(shown[0].street,'flop');assert.deepEqual(waits,[1500]);
});
test('unmount cancellation prevents revealing a result or requesting more bots',async()=>{
 const controller=new AbortController();let release,calls=0;const shown=[];
 const pending=play(state('ai1'),{signal:controller.signal,aiAction:async()=>{calls++;return state('ai2');},advance:()=>assert.fail(),onState:s=>shown.push(s),wait:()=>new Promise(resolve=>{release=resolve;})});
 controller.abort();release();await assert.rejects(pending);assert.equal(calls,1);assert.equal(shown.length,0);
});
test('slow calculation must finish as well as the pause; failures do not fabricate a move',async()=>{
 let resolveAI;const shown=[];const pending=play(state('ai1'),{signal:new AbortController().signal,aiAction:()=>new Promise(resolve=>{resolveAI=resolve;}),advance:()=>assert.fail(),onState:s=>shown.push(s),wait:async()=>{}});
 await flush();assert.equal(shown.length,0);resolveAI(state('hero'));await pending;assert.equal(shown.length,1);
 await assert.rejects(play(state('ai1'),{signal:new AbortController().signal,aiAction:async()=>{throw Error('offline');},advance:()=>assert.fail(),onState:()=>assert.fail(),wait:async()=>{}}),/offline/);
});
