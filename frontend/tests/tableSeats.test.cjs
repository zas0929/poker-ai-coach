const assert = require('node:assert/strict');
const { test } = require('node:test');
const ts = require('typescript');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../services/tableSeats.ts'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const sandbox = { exports: {} }; vm.runInNewContext(code, sandbox);
const { tableSeats } = sandbox.exports;
const player = id => ({id,name:id,stack:398,current_bet:2,cards:[{rank:'A',suit:'spades'}],status:'active',position:'button'});
const members = ['a','b','c'].map((player_id,seat) => ({player_id,seat,name:player_id,stack:500}));
const hand = {players:[player('a'),player('b')],result:null};

test('joining viewer takes a visible waiting seat without changing the hand or copying cards', () => {
  const before=JSON.stringify(hand);
  const seats=tableSeats(hand,2,'c',members);
  assert.equal(seats.length,3);
  assert.equal(seats[0].slot,'bottom');assert.equal(seats[0].player.id,'c');
  assert.equal(seats[0].waiting,true);assert.equal(seats[0].player.stack,500);
  assert.equal(seats[0].player.cards.length,0);assert.equal(seats[0].player.current_bet,0);
  assert.equal(new Set(seats.map(s=>s.player.id)).size,3);
  assert.equal(JSON.stringify(hand),before);
});
test('a waiting player becomes a normal participant only when included in the next hand',()=>{
  const seats=tableSeats({...hand,players:[...hand.players,player('c')]},3,'c',members);
  assert.equal(seats[0].waiting,false);assert.equal(seats[0].player.cards.length,1);
});
test('lobby shows occupied members rather than anonymous empty seats',()=>{
  const seats=tableSeats(null,2,'b',members.slice(0,2));
  assert.equal(seats[0].player.name,'b');assert.equal(seats[1].player.name,'a');
  assert.ok(seats.every(s=>s.waiting));
});
test('departing current-hand players still render and six-seat roster never duplicates a player',()=>{
  const seats=tableSeats(hand,2,'a',members.filter(m=>m.player_id!=='b'));
  assert.equal(seats.length,3);assert.ok(seats.some(s=>s.player.id==='b'));
  const six=Array.from({length:6},(_,seat)=>({player_id:String(seat),seat,name:String(seat),stack:400}));
  const full=tableSeats(null,2,'5',six);
  assert.equal(full.length,6);assert.equal(new Set(full.map(s=>s.player.id)).size,6);
});
test('a room creator occupies exactly one bottom seat before the first hand',()=>{
  const host={player_id:'host',seat:0,name:'Александр Длинноименный',stack:777};
  const seats=tableSeats(null,2,'host',[host]);
  assert.equal(seats[0].slot,'bottom');assert.equal(seats[0].player.name,host.name);
  assert.equal(seats[0].player.stack,777);assert.equal(seats[0].waiting,true);
  assert.equal(seats[1].player,undefined);
});
