'use client';

import { useI18n } from '@/i18n/LanguageProvider';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import PokerTable from '@/components/PokerTable';
import HandHistory from '@/components/HandHistory';
import { TrainingApi } from '@/services/trainingApi';
import type { Exercise, ExerciseKind, ExerciseResult, SavedDecision, TrainingProgress } from '@/services/trainingApi';
import type { ActionType } from '@/types/poker';

const ACTIONS: ActionType[] = ['fold', 'check', 'call', 'bet', 'raise'];

export default function PracticePage() {
  const { t, locale } = useI18n();
  const [kind, setKind] = useState<ExerciseKind>('call_price');
  const [question, setQuestion] = useState<Exercise | null>(null);
  const [progress, setProgress] = useState<TrainingProgress | null>(null);
  const [decisions, setDecisions] = useState<SavedDecision[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [result, setResult] = useState<ExerciseResult | null>(null);
  const [percent, setPercent] = useState('');
  const [actions, setActions] = useState<ActionType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef(false);
  const mounted = useRef(false);
  const attempt = useRef<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    void Promise.all([TrainingApi.next('call_price'), TrainingApi.progress(), TrainingApi.decisions()]).then(([next, stats, journal]) => {
      if (!mounted.current) return;
      setQuestion(next); setProgress(stats); setDecisions(journal.items); setCursor(journal.next_cursor);
    }).catch((cause) => { if (mounted.current) setError(cause instanceof Error ? cause.message : 'Could not load practice.'); })
      .finally(() => { if (mounted.current) setLoading(false); });
    return () => { mounted.current = false; };
  }, []);

  const run = async (task: () => Promise<void>) => {
    if (pending.current) return;
    pending.current = true; setLoading(true); setError(null);
    try { await task(); } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : 'Request failed.'); }
    finally { pending.current = false; if (mounted.current) setLoading(false); }
  };
  const applyQuestion = (next: Exercise) => {
    setQuestion(next); setKind(next.kind); setPercent(''); setActions([]); setResult(null); attempt.current = null;
  };
  const next = (nextKind: ExerciseKind) => run(async () => {
    const [exercise, stats] = await Promise.all([TrainingApi.next(nextKind, !result && question?.kind === nextKind ? question.question_id : undefined), TrainingApi.progress()]);
    if (mounted.current) { applyQuestion(exercise); setProgress(stats); }
  });
  const openExercise = (id: string) => run(async () => {
    const exercise = await TrainingApi.exercise(id);
    if (mounted.current) applyQuestion(exercise);
  });
  const submit = () => run(async () => {
    if (!question || result) return;
    attempt.current ??= crypto.randomUUID();
    const answer = await TrainingApi.answer({ question_id: question.question_id, attempt_id: attempt.current,
      ...(question.kind === 'call_price' ? { percent: Number(percent) } : { actions }) });
    if (mounted.current) setResult(answer);
    const stats = await TrainingApi.progress();
    if (mounted.current) setProgress(stats);
  });
  const retry = () => run(async () => {
    const [exercise, stats, journal] = await Promise.all([TrainingApi.next(kind), TrainingApi.progress(), TrainingApi.decisions()]);
    if (mounted.current) { applyQuestion(exercise); setProgress(stats); setDecisions(journal.items); setCursor(journal.next_cursor); }
  });
  const moreDecisions = () => run(async () => {
    if (!cursor) return;
    const page = await TrainingApi.decisions(cursor);
    if (mounted.current) { setDecisions((old) => [...old, ...page.items]); setCursor(page.next_cursor); }
  });
  const numericAnswer = Number(percent);
  const validAnswer = question?.kind === 'call_price'
    ? Boolean(percent.trim()) && Number.isFinite(numericAnswer) && numericAnswer >= 0 && numericAnswer <= 100
    : actions.length > 0;

  return (
    <main className="app-shell">
      <section className="top-bar"><div><p className="eyebrow">{t("Saved training · exact rules and call prices")}</p><h1>{t("Practice & decisions")}</h1></div><div className="status-row"><Link className="mode-link" href="/">{t("AI training")}</Link><Link className="mode-link" href="/friends">{t("Private tables")}</Link></div></section>
      <section className="session-strip practice-progress"><div><span>{t("Answered")}</span><strong>{progress?.attempts ?? 0}</strong></div><div><span>{t("Correct answers")}</span><strong>{progress?.correct_attempts ?? 0}</strong></div><div><span>{t("Questions correct on last try")}</span><strong>{progress?.last_answer_correct ?? 0}</strong></div><div><span>{t("Questions to review")}</span><strong>{progress?.to_review ?? 0}</strong></div></section>
      {error ? <div className="error-banner" role="alert"><span>{t(error)}</span><button disabled={loading} onClick={() => void retry()}>{t("Retry")}</button></div> : null}
      <section className="game-layout">
        <div className="table-column">
          <section className="control-panel practice-question">
            <div className="archive-heading"><h2>{t(question?.kind === 'legal_actions' ? 'Legal actions' : 'Call price')}</h2><label>{t("Exercise type")}<select disabled={loading} value={kind} onChange={(event) => void next(event.target.value as ExerciseKind)}><option value="call_price">{t("Call price")}</option><option value="legal_actions">{t("Legal actions")}</option></select></label></div>
            <p className="eyebrow">{t(question?.source ?? 'Loading practice')}</p><p>{t(question?.prompt ?? 'Loading your saved profile…')}</p>
            {question ? <p>{t("Pot: ")}{question.context.pot}{t(" · Call amount: ")}{question.context.call_amount}{t(question.context.uncalled_return ? ` · Uncallable chips returned: ${question.context.uncalled_return}` : '')}</p> : null}
            {question?.kind === 'legal_actions' ? <p className="room-note">{t("Highest bet: ")}{question.context.highest_bet}{t(" · Last full raise: ")}{question.context.last_full_raise} · {t(question.context.hero_acted_at_bet === null ? 'You have not acted on this street' : `You last acted at bet ${question.context.hero_acted_at_bet}`)}</p> : null}
            {question?.kind === 'call_price' ? <label className="practice-percent">{t("Your equity answer (%)")}<input type="number" min={0} max={100} step={0.1} inputMode="decimal" value={percent} disabled={loading || Boolean(result)} onChange={(event) => { setPercent(event.target.value); attempt.current = null; }} /></label> : <fieldset className="practice-actions" disabled={loading || Boolean(result)}><legend>{t("Select all allowed actions")}</legend>{ACTIONS.map((action) => <label key={action}><input type="checkbox" checked={actions.includes(action)} onChange={(event) => { setActions((old) => event.target.checked ? [...old, action] : old.filter((value) => value !== action)); attempt.current = null; }} />{t(action)}</label>)}</fieldset>}
            <div className="practice-buttons"><button className="primary-button" disabled={loading || !question || !validAnswer || Boolean(result)} onClick={() => void submit()}>{t("Check answer")}</button><button disabled={loading} onClick={() => void next(kind)}>{t(result ? 'Next exercise' : 'Skip exercise')}</button></div>
            {result ? <div className={`practice-feedback ${result.correct ? 'practice-correct' : 'practice-retry'}`} role="status"><h3>{t(result.correct ? 'Correct' : 'Review this answer')}</h3><p>{t(result.explanation)}</p>{result.tolerance_percentage_points !== null ? <small>{t("Accepted rounding: ±")}{t(result.tolerance_percentage_points)}{t(" percentage points.")}</small> : null}</div> : null}
          </section>
          <PokerTable hand={question?.hand ?? null} seatCount={question?.hand.players.length ?? 2} />
          <HandHistory hand={question?.hand ?? null} />
        </div>
        <aside className="side-column">
          <section className="control-panel"><h2>{t("How practice works")}</h2><p>{t("Incorrect answers return first, followed by unseen questions and then earlier correct answers.")}</p><p>{t("Real decisions you make against the AI create exercises automatically. This browser keeps its saved profile across restarts.")}</p><p className="room-note">{t("Call-price answers are checked mathematically. Legal actions use the betting rules. Strategic coach advice remains a heuristic; matching it is not a solver grade.")}</p></section>
          <section className="control-panel saved-decisions"><div className="archive-heading"><h2>{t("Saved AI decisions")}</h2><Link className="mode-link" href="/">{t("Play a hand")}</Link></div>
            {!decisions.length ? <p>{t("Your choices against the AI will appear here after you play.")}</p> : null}
            {decisions.map((decision) => <details key={decision.decision_id}><summary><strong>{t(decision.hand.street)} · {t(decision.chosen_action)}{t(decision.amount ? ` to ${decision.amount}` : '')}</strong><span>{t(decision.review.verdict === 'optimal' ? 'Matches coach heuristic' : 'Different from coach heuristic')}</span></summary><p>{t(new Date(decision.created_at.replace(' ', 'T')).toLocaleString(locale === 'en' ? 'en-US' : locale === 'uk' ? 'uk-UA' : 'ru-RU'))}{t(" · Hand ")}{t(decision.hand.hand_id.slice(0, 8))}</p><p>{t(decision.review.summary)}</p><div className="practice-buttons">{decision.exercises.call_price ? <button disabled={loading} onClick={() => void openExercise(decision.exercises.call_price!)}>{t("Practice call price")}</button> : null}{decision.exercises.legal_actions ? <button disabled={loading} onClick={() => void openExercise(decision.exercises.legal_actions!)}>{t("Practice actions")}</button> : null}</div></details>)}
            {cursor ? <button disabled={loading} onClick={() => void moreDecisions()}>{t("Load older decisions")}</button> : null}
          </section>
        </aside>
      </section>
    </main>
  );
}
