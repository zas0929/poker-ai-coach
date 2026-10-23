const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), ts = require('typescript');
const root = path.join(__dirname,'..');
function worker(network = async () => new Response('online')) {
 const handlers = {}, saved = new Map();
 const offline = new Response('offline screen');
 const cache = {addAll:async urls=>urls.forEach(url=>saved.set(url,offline)),match:async key=>saved.get(key)};
 const scope = {URL,Response,fetch:network,self:{location:{origin:'https://poker.example'},clients:{claim:async()=>{}},addEventListener:(name,fn)=>{handlers[name]=fn}},caches:{open:async()=>cache,keys:async()=>[],delete:async()=>true}};
 vm.runInNewContext(fs.readFileSync(path.join(root,'public/sw.js'),'utf8'),scope);
 return {saved,async install(){await new Promise((resolve,reject)=>handlers.install({waitUntil:p=>p.then(resolve,reject)}));},request(url,options={}){
  let result;handlers.fetch({request:{url,method:'GET',mode:'cors',headers:{get:()=>null},...options},respondWith:p=>{result=p;}});return result;
 }};
}
test('PWA navigation uses fresh network content and never saves private room HTML',async()=>{
 const w=worker();await w.install();
 const response=await w.request('https://poker.example/friends?room=PRIVATE',{mode:'navigate'});
 assert.equal(await response.text(),'online');assert.ok(!w.saved.has('/friends'));assert.ok(!w.saved.has('/'));
});
test('offline deep links get the public offline page; API, mutations, RSC and cross-origin traffic bypass the worker',async()=>{
 const w=worker(async()=>{throw new Error('offline');});await w.install();
 assert.equal(await (await w.request('https://poker.example/friends?room=PRIVATE',{mode:'navigate'})).text(),'offline screen');
 for(const [url,options] of [['https://api.example/api/hand/state',{}],['https://poker.example/api/rooms',{}],['https://poker.example/friends',{method:'POST'}],['https://poker.example/?_rsc=next',{}],['https://poker.example/',{headers:{get:name=>name==='RSC'?'1':null}}]]) assert.equal(w.request(url,options),undefined);
});
test('manifest has a stable identity, standalone display, correct icon sizes and maskable artwork',()=>{
 const scope={exports:{}};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root,'app/manifest.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,scope);
 const manifest=scope.exports.default();assert.equal(manifest.id,'/');assert.equal(manifest.scope,'/');assert.equal(manifest.display,'standalone');
 for(const size of [192,512]) assert.ok(manifest.icons.some(i=>i.sizes===`${size}x${size}`&&i.purpose==='any'));
 assert.ok(manifest.icons.some(i=>i.purpose==='maskable'));
 for(const icon of manifest.icons){const data=fs.readFileSync(path.join(root,'public',icon.src));const [w,h]=icon.sizes.split('x').map(Number);assert.equal(data.readUInt32BE(16),w);assert.equal(data.readUInt32BE(20),h);}
});
