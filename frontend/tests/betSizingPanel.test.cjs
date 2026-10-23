const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const read=file=>fs.readFileSync(path.join(__dirname,'..',file),'utf8');
const compile=source=>ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
function panel() {
 const sizing={exports:{}};vm.runInNewContext(compile(read('services/betSizing.ts')),sizing);
 const slots=[];let cursor=0;const actions=[];
 const jsx=(type,props)=>({type,props});
 const react={useId:()=>String(cursor),useState:initial=>{const i=cursor++;if(!(i in slots))slots[i]=initial;return[slots[i],value=>{slots[i]=value;}];}};
 const scope={exports:{},require:name=>name==='react'?react:name==='react/jsx-runtime'?{jsx,jsxs:jsx}:name.includes('betSizing')?sizing.exports:name.includes('LanguageProvider')?{useI18n:()=>({t:x=>x})}:name.includes('translate')?{displayPlayer:p=>p?.name??''}:{default:'Sheet'}};
 vm.runInNewContext(compile(read('components/ActionPanel.tsx')),scope);
 const hand={hand_id:'test',street:'river',pot:1061,history:[],players:[{id:'hero',stack:445,current_bet:0}],current_player_id:'hero',betting:{legal_actions:['fold','check','bet'],call_amount:0,min_bet:10,max_raise_to:445}};
 return {actions,render(analysis=null){cursor=0;return scope.exports.default({hand,analysis,isLoading:false,onAction:(...a)=>actions.push(a),onStartHand(){},onAdvance(){}});}};
}
function nodes(tree,predicate) {
 if(!tree||typeof tree!=='object')return[];
 if(Array.isArray(tree))return tree.flatMap(item=>nodes(item,predicate));
 return [...(predicate(tree)?[tree]:[]),...nodes(tree.props?.children,predicate)];
}
const field=tree=>nodes(tree,n=>n.type==='input'&&n.props.type==='number')[0];
const sizeButton=tree=>nodes(tree,n=>n.type==='button'&&n.props.className?.includes('size-action'))[0];
test('the real panel shows one minimum and one all-in preset and starts at 10',()=>{
 const p=panel(),tree=p.render();
 assert.equal(field(tree).props.value,'10');
 const presets=nodes(tree,n=>n.type==='button'&&'aria-pressed' in n.props);
 assert.equal(presets.length,2);assert.equal(presets.filter(p=>p.props['aria-pressed']).length,1);
 assert.equal(nodes(tree,n=>n.props?.className==='all-in-choice').length,0);
});
test('a late coach all-in recommendation cannot overwrite the open editor; custom 100 is sent unchanged',()=>{
 const p=panel();sizeButton(p.render()).props.onClick();
 let tree=p.render({recommended_action:'bet',recommended_amount:445});assert.equal(field(tree).props.value,'10');
 field(tree).props.onChange({target:{value:'100'}});tree=p.render({recommended_action:'bet',recommended_amount:445});assert.equal(field(tree).props.value,'100');
 const confirm=nodes(tree,n=>n.props?.className==='bet-confirm')[0];const button=nodes(confirm,n=>n.type==='button')[1];assert.equal(button.props.disabled,false);button.props.onClick();
 assert.deepEqual(p.actions,[['bet',100]]);
});
