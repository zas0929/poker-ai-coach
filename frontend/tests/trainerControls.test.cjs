const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const flush=()=>new Promise(setImmediate);
function fixture() {
 const slots=[];let index=0, resolveBot, rejectBot;
 const initial={hand_id:'one',street:'preflop',current_player_id:'hero',history:[],players:[{id:'hero',status:'active'}],betting:{legal_actions:['fold','call','raise'],call_amount:5}};
 const intermediate={...initial,current_player_id:null,history:[{action:'call'}],betting:{legal_actions:[]}};
 const next={...initial,street:'flop',betting:{legal_actions:['fold','check','bet'],call_amount:0}};
 const bot=new Promise((resolve,reject)=>{resolveBot=resolve;rejectBot=reject;});
 const react={useState(initial){const i=index++;if(!(i in slots))slots[i]=initial;return[slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;}];},useRef(initial){const i=index++;return slots[i]??(slots[i]={current:initial});},useCallback:fn=>fn,useEffect(){}};
 const playbackScope={exports:{},setTimeout,clearTimeout};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../services/trainerPlayback.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,playbackScope);
 const scope={exports:{},AbortController,require:name=>name==='react'?react:name.includes('trainerSolver')?{CurrentTrainerSolver:class{cancel(){}request(){return Promise.resolve();}}}:name.includes('latestAnalysis')?{LatestAnalysis:class{cancel(){}request(){return Promise.resolve();}}}:name.includes('trainerPlayback')?{playTrainerTurns:(state,options)=>playbackScope.exports.playTrainerTurns(state,{...options,wait:async()=>{}})}:name.includes('pokerApi')?{PokerApi:{startHand:async()=>initial,aiAction:()=>bot,advance:()=>bot,getState:async()=>intermediate}}:{TrainingApi:{action:async()=>({state:intermediate,review:{}})}}};
 const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../hooks/usePokerHand.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
 vm.runInNewContext(code,scope);
 return {initial,intermediate,next,read(){index=0;return scope.exports.usePokerHand();},resolveBot,rejectBot};
}
test('trainer keeps the same legal buttons while bots settle the street, then switches to the next decision',async()=>{
 const f=fixture();await f.read().startHand();
 const pending=f.read().action('call');await flush();
 const processing=f.read();assert.equal(processing.isLoading,true);assert.equal(processing.hand,f.intermediate);assert.equal(processing.actionHand,f.initial);
 assert.deepEqual(processing.actionHand.betting.legal_actions,['fold','call','raise']);
 f.resolveBot(f.next);await pending;
 assert.equal(f.read().isLoading,false);assert.equal(f.read().actionHand,f.next);
});
test('after a failed transition the controls use the recovered server state, not stale legal actions',async()=>{
 const f=fixture();await f.read().startHand();const pending=f.read().action('call');await flush();
 f.rejectBot(new Error('Bot transition failed'));await pending;
 assert.equal(f.read().isLoading,false);assert.equal(f.read().actionHand,f.intermediate);assert.deepEqual(f.read().actionHand.betting.legal_actions,[]);
});
