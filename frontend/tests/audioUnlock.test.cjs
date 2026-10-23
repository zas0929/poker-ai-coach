const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), ts = require('typescript');

function fixture() {
  const listeners = {}, effects = [], stateChanges = [], played = [];
  let clock = 0, finishResume, finishDecode;
  const resume = new Promise(resolve => { finishResume = resolve; });
  const decoded = new Promise(resolve => { finishDecode = resolve; });
  const param = { value:1, setValueAtTime(){}, exponentialRampToValueAtTime(){} };
  class Context {
    constructor() { this.state='suspended';this.currentTime=0;this.sampleRate=44100;Context.instance=this; }
    createGain(){return { gain:{...param},connect(){},disconnect(){} };}
    resume(){return resume.then(()=>{this.state='running';this.onstatechange?.();});}
    decodeAudioData(){return decoded;}
    createBufferSource(){return {connect(){},disconnect(){},start(){played.push('sample');}};}
    close(){this.state='closed';return Promise.resolve();}
  }
  const react = {
    createContext: value=>({Provider:'provider',value}), useCallback:fn=>fn,
    useContext:()=>{}, useRef:current=>({current}),
    useState:value=>[value,next=>stateChanges.push(next)], useEffect:fn=>effects.push(fn),
  };
  const scope = {exports:{},AudioContext:Context,Date:{now:()=>clock},
    localStorage:{getItem:()=>null,setItem(){}},
    window:{AudioContext:Context,addEventListener:(name,fn)=>{listeners[name]=fn;},removeEventListener(){}},
    fetch:async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(4)}),
    require:name=>name==='react'?react:name==='react/jsx-runtime'?{jsx:(_type,props)=>props}:name.includes('tableAudio')?{tableAudioSamples:()=>new Float32Array(1)}:{useI18n:()=>({t:x=>x})},
  };
  const source=fs.readFileSync(require('node:path').join(__dirname,'../components/TableSoundProvider.tsx'),'utf8');
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,scope);
  const value=scope.exports.TableSoundProvider({children:null}).value;
  const cleanup=effects.map(fn=>fn());
  return {value,listeners,played,stateChanges,context:()=>Context.instance,
    resume:async()=>{finishResume();await new Promise(setImmediate);},
    decode:async()=>{finishDecode({});await new Promise(setImmediate);},
    advance:ms=>{clock+=ms;},cleanup:()=>cleanup.forEach(fn=>fn?.())};
}

test('first gesture publishes audio readiness only after the browser resumes', async()=>{
  const f=fixture();
  assert.equal(f.value.ready,false);
  f.listeners.pointerdown();
  assert.equal(f.context().state,'suspended');
  await f.resume();
  assert.ok(f.stateChanges.includes(true));
  f.cleanup();
});

test('first chip sample survives a slow decode and mute prevents later playback',async()=>{
  const f=fixture();f.listeners.pointerdown();await f.resume();
  f.value.play('chips');f.advance(900);await f.decode();
  assert.equal(f.played.length,1);
  f.value.toggle();f.value.play('chips');await new Promise(setImmediate);
  assert.equal(f.played.length,1);
  f.cleanup();
});

test('muting while the first sample is decoding cancels that sound',async()=>{
  const f=fixture();f.listeners.pointerdown();await f.resume();
  f.value.play('chips');f.value.toggle();await f.decode();
  assert.equal(f.played.length,0);f.cleanup();
});
