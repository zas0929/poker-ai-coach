const {test}=require('node:test');
const assert=require('node:assert/strict');
const ts=require('typescript'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const scope={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../services/betSizing.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,scope);
const sizing=values=>JSON.parse(JSON.stringify(scope.exports.betSizing({action:'bet',pot:1061,highestBet:0,callAmount:0,minimum:10,maximum:445,stack:445,currentBet:0,...values})));
test('1061 pot and 445 stack: ordinary minimum plus one honestly labelled all-in, default is not all-in',()=>{
 const result=sizing({});assert.deepEqual(result.presets,[{label:'Min.',value:10,allIn:false},{label:'All in',value:445,allIn:true}]);
 assert.equal(result.defaultAmount,10);assert.equal(result.stackLimited,true);
});
test('normal stack retains actual pot fractions without misleading labels',()=>{
 assert.deepEqual(sizing({pot:120,maximum:1000,stack:1000}).presets.map(p=>[p.label,p.value]),[['1/2 pot',60],['2/3 pot',80],['Pot',120]]);
});
test('only the oversized fractions become one all-in, others remain available',()=>{
 assert.deepEqual(sizing({pot:600}).presets.map(p=>[p.label,p.value]),[['1/2 pot',300],['2/3 pot',400],['All in',445]]);
});
test('presets below a minimum are labelled minimum, not advertised as the wrong fraction',()=>{
 assert.deepEqual(sizing({pot:8}).presets,[{label:'Min.',value:10,allIn:false}]);
 const result=sizing({action:'raise',pot:300,highestBet:50,minimum:150,maximum:250,stack:250});
 assert.deepEqual(result.presets.map(p=>[p.label,p.value]),[['Min.',150],['All-in to',250]]);
});
test('short all-in below a normal minimum has exactly one choice and default',()=>{
 const result=sizing({minimum:7,maximum:7,stack:7});assert.equal(result.defaultAmount,7);assert.deepEqual(result.presets,[{label:'All in',value:7,allIn:true}]);
});
test('raises use total street bets including already committed chips and the call in a pot raise',()=>{
 const result=sizing({action:'raise',pot:300,highestBet:100,callAmount:80,currentBet:20,stack:425,minimum:200,maximum:445});
 assert.deepEqual(result.presets.map(p=>[p.label,p.value]),[['x2',200],['x3',300],['All-in to',445]]);
 assert.equal(result.presets.at(-1).value-20,425);
 const deep=sizing({action:'raise',pot:300,highestBet:100,callAmount:80,currentBet:20,stack:1000,minimum:200,maximum:1020});
 assert.equal(deep.presets.at(-1).value,480);
});
test('exact all-in is labelled honestly; explicit legal coach recommendation is preserved',()=>{
 assert.equal(sizing({pot:890}).presets.at(-1).label,'All in');
 assert.equal(sizing({recommended:445}).defaultAmount,445);
 for(const recommended of [0,446,10.5])assert.equal(sizing({recommended}).defaultAmount,10);
});
test('a non-stack upper limit is not called all-in and unavailable sizing yields no presets',()=>{
 assert.equal(sizing({maximum:200,stack:445}).presets.at(-1).label,'Max.');
 assert.equal(sizing({maximum:0}).presets.length,0);
});
test('all presets stay in legal bounds and unique across small pots and stacks',()=>{
 for(let stack=1;stack<500;stack+=13)for(let pot=0;pot<1600;pot+=47){
  const minimum=Math.min(10,stack),result=sizing({pot,stack,maximum:stack,minimum});
  assert.equal(new Set(result.presets.map(p=>p.value)).size,result.presets.length);
  assert.ok(result.presets.every(p=>Number.isInteger(p.value)&&p.value>=minimum&&p.value<=stack));
  assert.ok(result.defaultAmount>=minimum&&result.defaultAmount<=stack);
  assert.ok(result.presets.filter(p=>p.allIn).every(p=>p.label==='All in'&&p.value===stack));
 }
});
