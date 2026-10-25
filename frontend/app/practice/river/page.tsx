'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import AppHeader from '@/components/AppHeader';
import CardView from '@/components/CardView';
import { useI18n } from '@/i18n/LanguageProvider';
import type { Card } from '@/types/poker';
import { RiverLessonsApi, followLessonJob, lessonResultMatches, type RiverCatalog, type LessonJob } from '@/services/riverLessons';
import './river-lessons.css';

const SUITS = { s: 'spades', h: 'hearts', d: 'diamonds', c: 'clubs' } as const;
function card(text: string): Card { return { rank: text[0] as Card['rank'], suit: SUITS[text[1] as keyof typeof SUITS] }; }
function Cards({ text }: { text: string }) { return <span className="river-hand"><CardView card={card(text.slice(0, 2))} /><CardView card={card(text.slice(2))} /></span>; }
const REASONS: Record<string, string> = {
  QUALITY_GATE_FAILED: 'The strategy did not pass the quality check in this model. Action frequencies are withheld.',
  TIME_BUDGET_EXCEEDED: 'The calculation reached its time limit. You can try another example.',
  MEMORY_BUDGET_EXCEEDED: 'The calculation reached its memory limit. You can try another example.',
  NATIVE_KERNEL_UNAVAILABLE: 'The river calculation engine is unavailable.',
  STALE_DECISION: 'This calculation has expired. Start it again.',
  SHADOW_CANCELLED: 'Calculation cancelled.', ANALYSIS_CANCELLED: 'Calculation cancelled.',
  UNSUPPORTED_STATE_OR_TREE: 'This model is not supported by the calculation engine.',
};

export default function RiverLessonPage() {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<RiverCatalog | null>(null);
  const [selected, setSelected] = useState('river-1');
  const [job, setJob] = useState<LessonJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const revision = useRef(0);
  const pending = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const active = useRef<string | null>(null);
  const lesson = catalog?.lessons.find(item => item.id === selected);

  useEffect(() => {
    const abort = new AbortController();
    RiverLessonsApi.catalog(abort.signal).then(setCatalog).catch(cause => {
      if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load river examples.');
    });
    return () => { abort.abort(); };
  }, [retry]);
  useEffect(() => () => {
    revision.current++;
    controller.current?.abort();
    if (active.current) void RiverLessonsApi.cancel(active.current).catch(() => {});
  }, []);

  const stop = () => {
    revision.current++;
    controller.current?.abort();
    if (active.current) void RiverLessonsApi.cancel(active.current).catch(() => {});
    active.current = null; pending.current = false; setBusy(false); setJob(null);
  };
  const run = async () => {
    if (!lesson || !catalog?.version || pending.current) return;
    pending.current = true;
    const sequence = ++revision.current;
    const id = lesson.id; const version = catalog.version;
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError(null); setJob(null);
    let ticket: string | null = null;
    try {
      const submitted = await RiverLessonsApi.submit(id, version, abort.signal);
      ticket = submitted.ticket_id;
      if (sequence !== revision.current) { void RiverLessonsApi.cancel(ticket).catch(() => {}); return; }
      active.current = ticket;
      await followLessonJob(ticket, id, version, abort.signal, next => {
        if (sequence === revision.current) setJob(next);
      }, RiverLessonsApi.poll);
      if (sequence === revision.current) active.current = null;
    } catch (cause) {
      if (ticket) void RiverLessonsApi.cancel(ticket).catch(() => {});
      if (!abort.signal.aborted && sequence === revision.current) setError(cause instanceof Error ? cause.message : 'Could not complete the river calculation. Please retry.');
    } finally {
      if (sequence === revision.current) { active.current = null; pending.current = false; setBusy(false); }
    }
  };
  const action = (value: string) => {
    const [verb, amount] = value.toLowerCase().split(' ');
    return `${t(verb)}${amount ? ` ${amount}` : ''}`;
  };
  const result = job && lesson && catalog?.version && lessonResultMatches(job, lesson.id, catalog.version) ? job.result : null;
  const ready = result?.status === 'ready' && result.admission.offline_analysis_allowed && result.admission.live_advice_allowed === false && result.quality?.passed;
  const candidate = ready ? result.candidate : null;
  const reason = result?.reasons[0]?.code;

  return <main className="app-shell play-shell practice-shell river-lab">
    <AppHeader />
    <nav className="play-modes" aria-label={t('Game mode')}><Link href="/">{t('AI training')}</Link><Link href="/friends">{t('Play with friends')}</Link><Link href="/practice" aria-current="page">{t('Practice')}</Link></nav>
    <section className="river-intro"><div><Link className="mode-link" href="/practice">← {t('Back to practice')}</Link><p className="eyebrow">{t('Teaching model · river')}</p><h2>{t('River lesson')}</h2><p>{t('Explore a small, explicit model with one to five opponents. Run the calculation when you are ready.')}</p></div>
      {catalog?.enabled ? <label className="river-picker">{t('Opponents')}<select value={selected} onChange={event => { stop(); setSelected(event.target.value); setError(null); }}>{catalog.lessons.map(item => <option key={item.id} value={item.id}>{item.opponents}</option>)}</select></label> : null}
    </section>
    {error ? <div className="error-banner" role="alert"><span>{t(error)}</span><button onClick={() => { setError(null); if (catalog?.enabled) void run(); else setRetry(n => n+1); }}>{t('Retry')}</button></div> : null}
    {!catalog && !error ? <p role="status">{t('Loading river examples…')}</p> : null}
    {catalog && !catalog.enabled ? <section className="control-panel"><h2>{t('Local teaching feature')}</h2><p>{t('River calculation is not connected on this server.')}</p><p>{t('The current coach and other practice exercises remain available.')}</p><Link className="mode-link" href="/practice">{t('Back to practice')}</Link></section> : null}
    {lesson ? <div className="river-layout"><div className="river-main">
      <section className="control-panel river-model"><div className="river-section-title"><h3>{t('The decision')}</h3><span className="eyebrow">{t('river')}</span></div>
        <div className="river-cards"><div><p>{t('Board')}</p><div className="river-board">{lesson.board.map(text => <CardView key={text} card={card(text)} />)}</div></div><div><p>{t('Your hand')}</p><Cards text={lesson.own_hand} /></div></div>
        <dl className="river-facts"><div><dt>{t('Pot')}</dt><dd>{lesson.pot}</dd></div><div><dt>{t('Blinds')}</dt><dd>{lesson.small_blind}/{lesson.big_blind}</dd></div><div><dt>{t('Available bets')}</dt><dd>{lesson.tree.bet_sizes.join(' / ')}</dd></div><div><dt>{t('Future raises')}</dt><dd>{lesson.tree.max_raises}</dd></div></dl>
        <p className="room-note">{t('The river has not been bet yet. The player holding your hand acts first.')}</p>
      </section>
      <section className="control-panel river-result" aria-live="polite" aria-busy={busy}>
        <div className="river-section-title"><h3>{t('Model calculation')}</h3><div className="river-run-actions">{busy ? <button onClick={() => { stop(); setError(null); }}>{t('Cancel')}</button> : null}<button className="primary-button" disabled={busy} onClick={() => void run()}>{t(busy ? 'Calculating model…' : result ? 'Calculate again' : 'Calculate model')}</button></div></div>
        {busy ? <p role="status">{t(job?.state === 'queued' ? 'Waiting for the calculation slot…' : 'Calculating the strategy and checking its quality…')}</p> : !result ? <p>{t('Choose an example and start the calculation. The result will appear here.')}</p> : null}
        {result?.quality ? <p className="river-quality"><strong>{t('Quality in this model')}</strong><span>{result.quality.value.toFixed(3)}% {t('of the pot')} · {t('Threshold')}: {result.quality.gate}%</span></p> : null}
        {candidate ? <><h4>{t('Action frequencies')}</h4><div className="river-frequencies">{candidate.actions.map((label, index) => <div className="river-frequency" key={label}><span>{action(label)}</span><div className="river-frequency-track" aria-hidden="true"><i style={{ width: `${candidate.probabilities[index]*100}%` }} /></div><strong>{(candidate.probabilities[index]*100).toFixed(1)}%</strong></div>)}</div><p>{t('A mixed strategy can use several actions. These frequencies describe only the displayed ranges and bet sizes.')}</p></> : result ? <p role="status">{t(REASONS[reason ?? ''] ?? 'Could not complete the river calculation. Please retry.')}</p> : null}
        <p className="room-note">{t('Quality measures the best unilateral deviation inside this small model. Action EV and full-range GTO are not calculated here.')}</p>
      </section>
    </div><aside className="river-ranges control-panel"><h3>{t('Explicit ranges')}</h3><p className="room-note">{t('Each seat has two possible hands with relative weights. Opponent hands are assumptions, not revealed cards.')}</p>
      {lesson.players.map(player => <section className="river-range-player" key={player.id}><h4>{player.id === lesson.actor_id ? t('You · first to act') : `${t('Seat')} ${player.seat+1}`}{player.id === lesson.button_id ? ' · BTN' : ''}</h4><p>{t('Stack')}: <strong>{player.stack}</strong> · {t('Contributed')}: {player.total_committed}</p><ul>{player.range?.map(row => <li key={row.cards}><span className="river-combo">{row.cards.slice(0,2)} {row.cards.slice(2)}</span><span>{t('Weight')}: {row.weight.toFixed(3)}</span></li>)}</ul></section>)}
      <p className="room-note">{t('Card collisions are excluded jointly. Folded-card bunching and rake are not modelled. Examples do not change your game or saved decisions.')}</p>
    </aside></div> : null}
  </main>;
}
