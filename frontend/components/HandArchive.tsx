'use client';

import { useI18n } from '@/i18n/LanguageProvider';

import { useCallback, useEffect, useRef, useState } from 'react';
import PokerTable from '@/components/PokerTable';
import HandHistory from '@/components/HandHistory';
import CardView from '@/components/CardView';
import { HandArchiveApi } from '@/services/roomApi';
import type { ArchivedHand, ArchivedHandSummary, RoomCredentials } from '@/services/roomApi';

export default function HandArchive({ credentials, completedHandId }: {
  credentials: RoomCredentials; completedHandId: string | null;
}) {
  const { t, locale } = useI18n();
  const [items, setItems] = useState<ArchivedHandSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<ArchivedHand | null>(null);
  const listRequest = useRef<AbortController | null>(null);
  const detailRequest = useRef<AbortController | null>(null);

  const load = useCallback((before?: number) => {
    listRequest.current?.abort();
    const controller = new AbortController();
    listRequest.current = controller;
    void HandArchiveApi.list(credentials, controller.signal, before).then((page) => {
      if (controller.signal.aborted) return;
      setItems((previous) => before ? [...previous, ...page.items.filter((item) => !previous.some((old) => old.hand_id === item.hand_id))] : page.items);
      setNextCursor(page.next_cursor);
      setError(null);
    }).catch((cause) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load history.');
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
  }, [credentials]);

  useEffect(() => {
    void load();
    return () => listRequest.current?.abort();
  }, [load, completedHandId]);
  useEffect(() => () => detailRequest.current?.abort(), []);

  const openHand = async (handId: string) => {
    detailRequest.current?.abort();
    const controller = new AbortController();
    detailRequest.current = controller;
    setOpening(handId); setError(null);
    try {
      const hand = await HandArchiveApi.hand(credentials, handId, controller.signal);
      if (!controller.signal.aborted) setReview(hand);
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not open hand.');
    } finally { if (!controller.signal.aborted) setOpening(null); }
  };

  return (
    <section className="control-panel hand-archive">
      <div className="archive-heading"><h2>{t("Your hand history")}</h2><button disabled={loading} onClick={() => { setLoading(true); setError(null); void load(); }}>{t("Refresh")}</button></div>
      <p className="room-note">{t("Completed hands you played. Net result includes returned bets and split pots.")}</p>
      {error ? <p role="alert" className="archive-error">{t(error)}</p> : null}
      {!items.length ? <p>{t(loading ? 'Loading history…' : 'Play a hand to see its review here.')}</p> : null}
      <ol className="archive-list">{items.map((item) => (
        <li key={item.hand_id}>
          <button disabled={Boolean(opening)} onClick={() => void openHand(item.hand_id)}>
            <span><strong>{t(item.reason === 'showdown' ? 'Showdown' : 'Won by fold')} · {t(item.player_count)}{t(" players")}</strong><small>{t(new Date(item.completed_at.replace(' ', 'T')).toLocaleString(locale === 'uk' ? 'uk-UA' : 'ru-RU'))} · {t(item.hand_id.slice(0, 8))}</small></span>
            <em className={item.net >= 0 ? 'archive-profit' : 'archive-loss'}>{t(opening === item.hand_id ? 'Opening…' : `${item.net > 0 ? '+' : ''}${item.net}`)}</em>
          </button>
        </li>
      ))}</ol>
      {nextCursor ? <button disabled={loading} onClick={() => { setLoading(true); setError(null); void load(nextCursor); }}>{t("Load older hands")}</button> : null}
      {review ? <HandReview key={review.hand_id} review={review} onClose={() => setReview(null)} /> : null}
    </section>
  );
}

function HandReview({ review, onClose }: { review: ArchivedHand; onClose: () => void }) {
  const { t } = useI18n();
  const dialog = useRef<HTMLDialogElement>(null);
  const [index, setIndex] = useState(review.frames.length - 1);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  const frame = review.frames[index];
  const result = review.hand.result!;
  const ownResult = result.player_results.find((player) => player.player_id === review.viewer_id);
  const committed = review.hand.contributions?.[review.viewer_id] ?? 0;
  const won = ownResult?.amount_won ?? 0;
  const net = won - committed;
  const name = (id: string) => review.hand.players.find((player) => player.id === id)?.name ?? id;
  const facts = frame.decision;
  const frameLabel = (step: ArchivedHand['frames'][number]) => {
    const actor = step.hand.players.find(player => player.id === step.hand.current_player_id);
    if (!actor) return t(step.label);
    const prefix = `${step.hand.street} · ${actor.name}: `;
    return step.label.startsWith(prefix)
      ? `${t(step.hand.street)} · ${actor.name}: ${t(step.label.slice(prefix.length))}`
      : step.label;
  };

  return (
    <dialog ref={dialog} className="hand-review-dialog" aria-labelledby="hand-review-title" onCancel={onClose}>
      <div className="archive-heading review-header"><div><p className="eyebrow">{t("Archived hand · ")}{t(review.hand_id.slice(0, 8))}</p><h2 id="hand-review-title">{t("Hand review")}</h2><p>{t("The live table continues while this review is open.")}</p></div><button autoFocus onClick={onClose}>{t("Close review")}</button></div>
      {review.warning ? <p role="status" className="archive-error">{t(review.warning)}</p> : null}
      <div className="review-totals"><span>{t("Committed ")}<strong>{committed}</strong></span><span>{t("Received ")}<strong>{won}</strong></span><span>{t("Net ")}<strong className={net >= 0 ? 'archive-profit' : 'archive-loss'}>{t(net > 0 ? '+' : '')}{net}</strong></span><span>{t("Total awarded ")}<strong>{result.pot_awarded}</strong></span></div>
      <nav className="replay-controls" aria-label={t("Replay navigation")}>
        <button disabled={index === 0} onClick={() => setIndex(0)}>{t("First")}</button>
        <button disabled={index === 0} onClick={() => setIndex(index - 1)}>{t("Previous")}</button>
        <label>{t("Replay step")}<select value={index} onChange={(event) => setIndex(Number(event.target.value))}>{review.frames.map((step, i) => <option key={i} value={i}>{t(i + 1)}. {frameLabel(step)}</option>)}</select></label>
        <button disabled={index === review.frames.length - 1} onClick={() => setIndex(index + 1)}>{t("Next")}</button>
        <button disabled={index === review.frames.length - 1} onClick={() => setIndex(review.frames.length - 1)}>{t("Result")}</button>
      </nav>
      <p className="replay-caption">{index === review.frames.length - 1 ? t('Saved result') : t('Before the recorded action: {0}').replace('{0}', frameLabel(frame))}</p>
      <div className="review-layout">
        <div><PokerTable hand={frame.hand} seatCount={frame.hand.players.length} viewerId={review.viewer_id} /></div>
        <aside className="review-facts">
          {facts ? <section className="control-panel"><h3>{t("Your decision")}</h3><p>{t(facts.description)}</p><dl><div><dt>{t("Pot before action")}</dt><dd>{t(facts.pot_before)}</dd></div><div><dt>{t("Your stack")}</dt><dd>{t(facts.stack_before)}</dd></div><div><dt>{t("Call amount")}</dt><dd>{t(facts.call_amount)}</dd></div><div><dt>{t("Chips committed by action")}</dt><dd>{t(facts.committed_by_action)}</dd></div><div><dt>{t("Made hand at the time")}</dt><dd>{t(facts.made_hand.replaceAll('_', ' '))}</dd></div>{facts.break_even_equity !== null ? <div><dt>{t("Break-even call equity")}</dt><dd>{t((facts.break_even_equity * 100).toFixed(1))}%</dd></div> : null}</dl><p className="room-note">{t(facts.note)}</p></section> : index < review.frames.length - 1 ? <p className="room-note">{t("Opponent action from the public hand log. Their private cards remain hidden.")}</p> : null}
          {index === review.frames.length - 1 ? <section className="control-panel"><h3>{t("Pots and payouts")}</h3>{result.pots?.map((pot, i) => <div className="review-pot" key={i}><strong>{t(i ? `Side pot ${i}` : 'Main pot')} · {t(pot.amount)}</strong><p>{t("Eligible: ")}{t(pot.eligible_player_ids.map(name).join(', '))}</p>{Object.entries(pot.awards).map(([id, amount]) => <p key={id}>{name(id)}{t(" receives ")}{amount}</p>)}</div>)}</section> : null}
          <section className="control-panel"><h3>{t("Board at this step")}</h3><div className="review-board">{frame.hand.board.map((card, i) => <CardView key={i} card={card} />)}{!frame.hand.board.length ? <p>{t("Preflop")}</p> : null}</div><p className="room-note">{t(review.review_note)}</p></section>
          <HandHistory hand={frame.hand} />
        </aside>
      </div>
    </dialog>
  );
}
