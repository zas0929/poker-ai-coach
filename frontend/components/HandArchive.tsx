'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import PokerTable from '@/components/PokerTable';
import HandHistory from '@/components/HandHistory';
import CardView from '@/components/CardView';
import { HandArchiveApi } from '@/services/roomApi';
import type { ArchivedHand, ArchivedHandSummary, RoomCredentials } from '@/services/roomApi';

export default function HandArchive({ credentials, completedHandId }: {
  credentials: RoomCredentials; completedHandId: string | null;
}) {
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
      <div className="archive-heading"><h2>Your hand history</h2><button disabled={loading} onClick={() => { setLoading(true); setError(null); void load(); }}>Refresh</button></div>
      <p className="room-note">Completed hands you played. Net result includes returned bets and split pots.</p>
      {error ? <p role="alert" className="archive-error">{error}</p> : null}
      {!items.length ? <p>{loading ? 'Loading history…' : 'Play a hand to see its review here.'}</p> : null}
      <ol className="archive-list">{items.map((item) => (
        <li key={item.hand_id}>
          <button disabled={Boolean(opening)} onClick={() => void openHand(item.hand_id)}>
            <span><strong>{item.reason === 'showdown' ? 'Showdown' : 'Won by fold'} · {item.player_count} players</strong><small>{new Date(item.completed_at.replace(' ', 'T')).toLocaleString()} · {item.hand_id.slice(0, 8)}</small></span>
            <em className={item.net >= 0 ? 'archive-profit' : 'archive-loss'}>{opening === item.hand_id ? 'Opening…' : `${item.net > 0 ? '+' : ''}${item.net}`}</em>
          </button>
        </li>
      ))}</ol>
      {nextCursor ? <button disabled={loading} onClick={() => { setLoading(true); setError(null); void load(nextCursor); }}>Load older hands</button> : null}
      {review ? <HandReview key={review.hand_id} review={review} onClose={() => setReview(null)} /> : null}
    </section>
  );
}

function HandReview({ review, onClose }: { review: ArchivedHand; onClose: () => void }) {
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

  return (
    <dialog ref={dialog} className="hand-review-dialog" aria-labelledby="hand-review-title" onCancel={onClose}>
      <div className="archive-heading review-header"><div><p className="eyebrow">Archived hand · {review.hand_id.slice(0, 8)}</p><h2 id="hand-review-title">Hand review</h2><p>The live table continues while this review is open.</p></div><button autoFocus onClick={onClose}>Close review</button></div>
      {review.warning ? <p role="status" className="archive-error">{review.warning}</p> : null}
      <div className="review-totals"><span>Committed <strong>{committed}</strong></span><span>Received <strong>{won}</strong></span><span>Net <strong className={net >= 0 ? 'archive-profit' : 'archive-loss'}>{net > 0 ? '+' : ''}{net}</strong></span><span>Total awarded <strong>{result.pot_awarded}</strong></span></div>
      <nav className="replay-controls" aria-label="Replay navigation">
        <button disabled={index === 0} onClick={() => setIndex(0)}>First</button>
        <button disabled={index === 0} onClick={() => setIndex(index - 1)}>Previous</button>
        <label>Replay step<select value={index} onChange={(event) => setIndex(Number(event.target.value))}>{review.frames.map((step, i) => <option key={i} value={i}>{i + 1}. {step.label}</option>)}</select></label>
        <button disabled={index === review.frames.length - 1} onClick={() => setIndex(index + 1)}>Next</button>
        <button disabled={index === review.frames.length - 1} onClick={() => setIndex(review.frames.length - 1)}>Result</button>
      </nav>
      <p className="replay-caption">{index === review.frames.length - 1 ? 'Saved result' : `Before the recorded action: ${frame.label}`}</p>
      <div className="review-layout">
        <div><PokerTable hand={frame.hand} seatCount={frame.hand.players.length} viewerId={review.viewer_id} /></div>
        <aside className="review-facts">
          {facts ? <section className="control-panel"><h3>Your decision</h3><p>{facts.description}</p><dl><div><dt>Pot before action</dt><dd>{facts.pot_before}</dd></div><div><dt>Your stack</dt><dd>{facts.stack_before}</dd></div><div><dt>Call amount</dt><dd>{facts.call_amount}</dd></div><div><dt>Chips committed by action</dt><dd>{facts.committed_by_action}</dd></div><div><dt>Made hand at the time</dt><dd>{facts.made_hand.replaceAll('_', ' ')}</dd></div>{facts.break_even_equity !== null ? <div><dt>Break-even call equity</dt><dd>{(facts.break_even_equity * 100).toFixed(1)}%</dd></div> : null}</dl><p className="room-note">{facts.note}</p></section> : index < review.frames.length - 1 ? <p className="room-note">Opponent action from the public hand log. Their private cards remain hidden.</p> : null}
          {index === review.frames.length - 1 ? <section className="control-panel"><h3>Pots and payouts</h3>{result.pots?.map((pot, i) => <div className="review-pot" key={i}><strong>{i ? `Side pot ${i}` : 'Main pot'} · {pot.amount}</strong><p>Eligible: {pot.eligible_player_ids.map(name).join(', ')}</p>{Object.entries(pot.awards).map(([id, amount]) => <p key={id}>{name(id)} receives {amount}</p>)}</div>)}</section> : null}
          <section className="control-panel"><h3>Board at this step</h3><div className="review-board">{frame.hand.board.map((card, i) => <CardView key={i} card={card} />)}{!frame.hand.board.length ? <p>Preflop</p> : null}</div><p className="room-note">{review.review_note}</p></section>
          <HandHistory hand={frame.hand} />
        </aside>
      </div>
    </dialog>
  );
}
