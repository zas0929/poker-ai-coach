'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import AppHeader from '@/components/AppHeader';
import CardView from '@/components/CardView';
import { useI18n } from '@/i18n/LanguageProvider';
import type { Card } from '@/types/poker';
import { RiverLessonsApi, RiverHistoryApi, HISTORY_REASONS, followLessonJob, lessonActionValues,
  type HistoryRiverDecision, type HistoryRiverAssessment, type HistoryRiverModel, type LessonJob } from '@/services/riverLessons';
import '../river-lessons.css';

const SUITS = {s:'spades',h:'hearts',d:'diamonds',c:'clubs'} as const;
function card(code: string): Card { return {rank:code[0] as Card['rank'],suit:SUITS[code[1] as keyof typeof SUITS]}; }
const amount = (value: number) => `${value >= .005 ? '+' : ''}${(Math.abs(value)<.005 ? 0 : value).toFixed(2)}`;

export default function RiverHistoryPage() {
  const {t,locale} = useI18n();
  const [items,setItems]=useState<HistoryRiverDecision[]>([]);
  const [cursor,setCursor]=useState<number|null>(null);
  const [selected,setSelected]=useState<number|null>(null);
  const [assessment,setAssessment]=useState<HistoryRiverAssessment|null>(null);
  const [ranges,setRanges]=useState<Record<string,string>>({});
  const [bets,setBets]=useState('');const [raises,setRaises]=useState('');const [raiseEnabled,setRaiseEnabled]=useState(false);
  const [job,setJob]=useState<LessonJob|null>(null);
  const [loading,setLoading]=useState(true);const [busy,setBusy]=useState(false);const [dirty,setDirty]=useState(false);
  const [error,setError]=useState<string|null>(null);const [reload,setReload]=useState(0);
  const sequence=useRef(0);const pending=useRef(false);const abort=useRef<AbortController|null>(null);const ticket=useRef<string|null>(null);
  const listing=useRef(false);const moreAbort=useRef<AbortController|null>(null);

  useEffect(()=>{
    const controller=new AbortController();
    RiverHistoryApi.list(undefined,controller.signal).then(page=>{
      if(controller.signal.aborted)return;
      setItems(page.items);setCursor(page.next_cursor);setSelected(old=>page.items.some(item=>item.decision_id===old)?old:page.items[0]?.decision_id??null);
    }).catch(cause=>{if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:'Saved river history is unavailable.');})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>{controller.abort();moreAbort.current?.abort();};
  },[reload]);
  useEffect(()=>{
    if(selected===null)return;
    const revision=++sequence.current;const controller=new AbortController();abort.current=controller;
    RiverHistoryApi.detail(selected,controller.signal).then(next=>{
      if(controller.signal.aborted||revision!==sequence.current)return;
      setAssessment(next);setRanges(Object.fromEntries(Object.entries(next.model.selected_hands).map(([id,hands])=>[id,hands.join(' ')])));
      setBets(next.model.bet_sizes.join(' '));setRaises(next.model.raise_sizes.join(' '));setRaiseEnabled(Boolean(next.model.max_raises));setDirty(false);
    }).catch(cause=>{if(!controller.signal.aborted&&revision===sequence.current)setError(cause instanceof Error?cause.message:'This saved decision cannot be reconstructed safely.');});
    return()=>controller.abort();
  },[selected,reload]);
  useEffect(()=>()=>{sequence.current++;abort.current?.abort();if(ticket.current)void RiverLessonsApi.cancel(ticket.current).catch(()=>{});},[]);

  const stop=()=>{sequence.current++;abort.current?.abort();if(ticket.current)void RiverLessonsApi.cancel(ticket.current).catch(()=>{});ticket.current=null;pending.current=false;setBusy(false);setJob(null);};
  const edit=(change:()=>void)=>{stop();change();setDirty(true);setError(null);};
  const choose=(id:number)=>{stop();setAssessment(null);setError(null);setSelected(id);};
  const run=async()=>{
    if(!assessment||selected===null||pending.current)return;
    const parse=(text:string)=>text.trim()?text.trim().split(/[\s,]+/):[];
    const selected_hands=Object.fromEntries(Object.entries(ranges).map(([id,text])=>[id,parse(text).map(c=>c.length===4?c[0].toUpperCase()+c[1].toLowerCase()+c[2].toUpperCase()+c[3].toLowerCase():c)]));
    const sizes=(text:string)=>parse(text).map(Number);
    const model:HistoryRiverModel={selected_hands,bet_sizes:sizes(bets),raise_sizes:raiseEnabled?sizes(raises):[],max_raises:raiseEnabled?1:0};
    if(Object.values(selected_hands).some(h=>h.length!==2||h.some(c=>!/^([2-9TJQKA][cdhs]){2}$/.test(c)))){setError('Choose exactly two distinct hands for every live seat.');return;}
    if([model.bet_sizes,...(raiseEnabled?[model.raise_sizes]:[])].some(v=>v.length<1||v.length>2||v.some(n=>!Number.isInteger(n)||n<1||n>10000))){setError('Use one or two positive integer sizes, up to 10000.');return;}
    pending.current=true;const revision=++sequence.current;const controller=new AbortController();abort.current=controller;
    setBusy(true);setJob(null);setError(null);let current:string|null=null;
    try{
      const submitted=await RiverHistoryApi.submit(selected,assessment.source_version,model,controller.signal);
      current=submitted.ticket_id;
      if(revision!==sequence.current){if(current)void RiverLessonsApi.cancel(current).catch(()=>{});return;}
      setAssessment(submitted.assessment);setDirty(false);
      if(!current)return;
      if(!submitted.lesson_id||!submitted.version||submitted.assessment.decision_id!==selected||submitted.assessment.source_version!==assessment.source_version)throw new Error('This calculation has expired. Start it again.');
      ticket.current=current;
      await followLessonJob(current,submitted.lesson_id,submitted.version,controller.signal,next=>{if(revision===sequence.current)setJob(next);},RiverLessonsApi.poll);
    }catch(cause){if(current)void RiverLessonsApi.cancel(current).catch(()=>{});if(!controller.signal.aborted&&revision===sequence.current)setError(cause instanceof Error?cause.message:'Could not complete the river calculation. Please retry.');}
    finally{if(revision===sequence.current){pending.current=false;ticket.current=null;setBusy(false);}}
  };
  const more=async()=>{
    if(cursor===null||listing.current)return;listing.current=true;
    const controller=new AbortController();moreAbort.current=controller;
    try{const page=await RiverHistoryApi.list(cursor,controller.signal);if(!controller.signal.aborted){setItems(old=>[...old,...page.items]);setCursor(page.next_cursor);}}
    catch(cause){if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:'Saved river history is unavailable.');}finally{listing.current=false;}
  };
  const lesson=assessment?.lesson;
  const result=!dirty&&job?.lesson_id===lesson?.id&&job?.version===assessment?.version?job?.result:null;
  const values=lessonActionValues(result,lesson);
  const candidate=values?result?.candidate:null;
  const action=(label:string)=>{const [verb,size]=label.toLowerCase().split(' ');return `${t(verb)}${size?` ${size}`:''}`;};
  const seatName=(id:string)=>id==='hero'?t('You'):`${t('Seat')} ${(lesson?.players.find(p=>p.id===id)?.seat??0)+1}`;
  const heuristic=assessment?.heuristic_action?assessment.heuristic_action.toUpperCase()+(assessment.heuristic_amount?` ${assessment.heuristic_amount}`:''):null;
  const chosen=assessment?assessment.chosen_action.toUpperCase()+(assessment.chosen_amount!==null&&['bet','raise'].includes(assessment.chosen_action)?` ${assessment.chosen_amount}`:''):'';

  return <main className="app-shell play-shell practice-shell river-lab">
    <AppHeader/><nav className="play-modes" aria-label={t('Game mode')}><Link href="/">{t('AI training')}</Link><Link href="/friends">{t('Play with friends')}</Link><Link href="/practice">{t('Practice')}</Link></nav>
    <section className="river-intro"><div><Link href="/practice/river" className="mode-link">← {t('River lesson')}</Link><h2>{t('Completed river decisions')}</h2><p>{t('Review your saved river choice after the hand ends. Opponent cards and later actions are not used to build the model.')}</p></div><button onClick={()=>{stop();setAssessment(null);setLoading(true);setError(null);setReload(n=>n+1);}}>{t('Refresh history')}</button></section>
    {error?<div className="error-banner" role="alert">{t(error)}</div>:null}
    {loading?<p role="status">{t('Loading saved river decisions…')}</p>:null}
    {!loading&&!error&&!items.length?<section className="control-panel"><p>{t('No completed river decisions are indexed yet. Play a trainer hand through the river and finish it. Older decisions without completion evidence are not imported.')}</p><Link href="/" className="mode-link">{t('Play a hand')}</Link></section>:null}
    {items.length?<label className="river-history-picker">{t('Saved decision')}<select value={selected??''} onChange={e=>choose(Number(e.target.value))}>{items.map(item=><option key={item.decision_id} value={item.decision_id}>{new Date(item.created_at).toLocaleString(locale==='uk'?'uk-UA':locale==='ru'?'ru-RU':'en-US')} · {item.hand_id.slice(0,8)} · {action(item.chosen_action.toUpperCase()+(item.amount?` ${item.amount}`:''))}</option>)}</select></label>:null}
    {cursor!==null?<button onClick={()=>void more()}>{t('Load older decisions')}</button>:null}
    {selected!==null&&!assessment&&!error?<p role="status">{t('Preparing the saved decision…')}</p>:null}
    {assessment&&lesson?<div className="river-layout"><div className="river-main">
      <section className="control-panel river-model"><h3>{t('The decision')}</h3><div className="river-cards"><div><p>{t('Board')}</p><div className="river-board">{lesson.board.map(c=><CardView key={c} card={card(c)}/>)}</div></div><div><p>{t('Your hand')}</p><div className="river-hand">{[lesson.own_hand.slice(0,2),lesson.own_hand.slice(2)].map(c=><CardView key={c} card={card(c)}/>)}</div></div></div><p>{t('Pot')}: <strong>{lesson.pot}</strong> · {t('Blinds')}: {lesson.small_blind}/{lesson.big_blind}</p><p>{t('Your recorded action')}: <strong>{action(chosen)}</strong></p>{heuristic?<p>{t('Heuristic advice at that moment')}: <strong>{action(heuristic)}</strong></p>:null}<p className="room-note">{t('This is the original decision snapshot. The result of the hand is not an input to this calculation.')}</p></section>
      <section className="control-panel river-history-settings"><h3>{t('Explicit model settings')}</h3><p className="room-note">{t('Suggestions are arbitrary reproducible subsets, not representative ranges. Change them before calculating. Your range must retain your saved hand and an alternative.')}</p>
        {Object.entries(ranges).map(([id,text])=><label key={id}>{id==='hero'?t('Your assumed range'):seatName(id)}<input value={text} spellCheck={false} autoCapitalize="off" onChange={e=>edit(()=>setRanges(old=>({...old,[id]:e.target.value})))}/></label>)}
        <label>{t('Bet totals')}<input value={bets} inputMode="numeric" onChange={e=>edit(()=>setBets(e.target.value))}/></label>
        <label className="river-raise-toggle"><input type="checkbox" checked={raiseEnabled} onChange={e=>edit(()=>setRaiseEnabled(e.target.checked))}/>{t('Allow one future raise')}</label>
        {raiseEnabled?<label>{t('Raise-to totals')}<input value={raises} inputMode="numeric" onChange={e=>edit(()=>setRaises(e.target.value))}/></label>:null}
        <p className="room-note">{t('Two four-character combinations per live seat, for example AsKd 7h7d. Sizes are total street bets; at most two sizes and one future raise are supported.')}</p>
        <div className="river-run-actions">{busy?<button onClick={()=>stop()}>{t('Cancel')}</button>:null}<button className="primary-button" disabled={busy} onClick={()=>void run()}>{t(busy?'Calculating model…':'Calculate selected model')}</button></div>
      </section>
      <section className="control-panel river-result" aria-live="polite" aria-busy={busy}><h3>{t('Model calculation')}</h3>
        {dirty&&!busy?<p>{t('Settings changed. Calculate again to compare this model.')}</p>:!dirty&&!assessment.supported?<p role="status">{t(HISTORY_REASONS[assessment.reason??'']??'This model is not supported by the calculation engine.')}</p>:null}
        {busy?<p role="status">{t('Calculating the strategy and checking its quality…')}</p>:null}
        {values&&candidate?<><table className="river-action-table"><thead><tr><th scope="col">{t('Action')}</th><th scope="col">{t('Frequency')}</th><th scope="col">{t('EV · chips')}</th><th scope="col">{t('Behind best · chips')}</th></tr></thead><tbody>{values.actions.map((label,i)=><tr key={label} className={label===chosen?'river-chosen':''}><th scope="row">{action(label)}{label===chosen?<small>{t('Your action')}</small>:null}</th><td>{(candidate.probabilities[i]*100).toFixed(1)}%</td><td className="river-ev">{amount(values.ev_chips[i])}</td><td>{values.gap_to_best_chips[i]<.005?'≈0':values.gap_to_best_chips[i].toFixed(2)}</td></tr>)}</tbody></table><p className="river-policy-ev">{t('EV of the mixed strategy')}: <strong>{amount(values.policy_ev_chips)} {t('chips')}</strong></p>{!values.actions.includes(chosen)?<p>{t('Your recorded action is outside this tree. No EV grade is assigned to it.')}</p>:null}<p>{t('EV is the expected change in your stack from this decision. Earlier contributions are already spent; future payments are deducted from receipts, including refunds.')}</p><p className="room-note">{t('After each first action, every player follows the same calculated strategy. The gap compares these first actions with that fixed continuation; it is not a full best response or a guarantee of profit.')}</p></>:result&&!busy?<p>{t('This model did not produce an admitted EV result. Try different assumptions or fewer future raises.')}</p>:null}
        {result?.quality?<p className="river-quality">{t('Quality in this model')}: {result.quality.value.toFixed(3)}% · {t('Threshold')}: {result.quality.gate}%</p>:null}
      </section>
    </div><aside className="control-panel river-ranges"><h3>{t('Model coverage')}</h3><p>{t('This is a tiny selected game, not a solution of the full ranges. Coverage is the selected share of each public range weight before joint card-collision checks.')}</p>
      {!dirty?assessment.coverage.map(row=><section key={row.player_id} className="river-range-player"><h4>{seatName(row.player_id)}</h4><p>{t('Stack')}: {lesson.players.find(p=>p.id===row.player_id)?.stack} · {t('Contributed')}: {lesson.players.find(p=>p.id===row.player_id)?.total_committed}</p><p>{row.selected_combos} / {row.public_combos} · {(row.weight_share*100).toFixed(2)}%</p><ul>{lesson.players.find(p=>p.id===row.player_id)?.range?.map(r=><li key={r.cards}><span className="river-combo">{r.cards}</span><span>{t('Weight')}: {r.weight.toFixed(3)}</span></li>)}</ul></section>):null}
      {!dirty&&assessment.supported?<p>{t('Compatible joint deals')}: {assessment.joint_deals} · {t('Public tree nodes')}: {assessment.public_nodes}</p>:null}
      <p className="room-note">{t('Quality measures the best unilateral deviation inside this small model. It does not establish full-range GTO or the accuracy of the assumed ranges.')}</p>
    </aside></div>:null}
  </main>;
}
