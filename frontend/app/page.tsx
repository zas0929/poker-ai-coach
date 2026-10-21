'use client';

import { useState } from 'react';

import ActionPanel from '@/components/ActionPanel';
import CoachPanel from '@/components/CoachPanel';
import HandHistory from '@/components/HandHistory';
import PokerTable from '@/components/PokerTable';
import { usePokerHand } from '@/hooks/usePokerHand';

export default function HomePage() {
  const [seatCount, setSeatCount] = useState(2);
  const {
    analysis,
    actionReview,
    decisionLog,
    error,
    hand,
    isLoading,
    action,
    advance,
    analyze,
    clearError,
    startHand,
  } = usePokerHand();

  return (
    <main className="app-shell">
      <section className="top-bar">
        <div>
          <p className="eyebrow">Texas Hold'em AI Coach</p>
          <h1>Poker AI Coach</h1>
        </div>
        <div className="status-row">
          <label className="seat-count-control">
            <span>Seats</span>
            <select value={seatCount} onChange={(event) => setSeatCount(Number(event.target.value))}>
              {[2, 3, 4, 5, 6].map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </label>
          <span className="status-pill">{hand?.street ?? 'not started'}</span>
          <button className="primary-button" onClick={startHand} disabled={isLoading}>
            New hand
          </button>
        </div>
      </section>

      <SessionStrip hand={hand} />

      {error ? (
        <div className="error-banner">
          <span>{error}</span>
          <button onClick={clearError}>Dismiss</button>
        </div>
      ) : null}

      <section className="game-layout">
        <div className="table-column">
          <PokerTable hand={hand} seatCount={seatCount} />
          <ActionPanel
            analysis={analysis}
            hand={hand}
            isLoading={isLoading}
            onAction={action}
            onAdvance={advance}
            onAnalyze={analyze}
            onStartHand={startHand}
          />
        </div>
        <aside className="side-column">
          <CoachPanel
            analysis={analysis}
            actionReview={actionReview}
            decisionLog={decisionLog}
            hand={hand}
            isLoading={isLoading}
          />
          <HandHistory hand={hand} />
        </aside>
      </section>
    </main>
  );
}

function SessionStrip({ hand }: { hand: ReturnType<typeof usePokerHand>['hand'] }) {
  const hero = hand?.players.find((player) => player.id === 'hero');
  const villain = hand?.players.find((player) => player.id === 'villain');
  const heroTotal = (hero?.stack ?? 0) + (hero?.current_bet ?? 0);
  const villainTotal = (villain?.stack ?? 0) + (villain?.current_bet ?? 0);
  const net = heroTotal - villainTotal;
  const leader = net === 0 ? 'Even' : net > 0 ? 'You' : 'AI';
  const button = hand?.dealer_player_id === 'hero' ? 'You' : hand?.dealer_player_id === 'villain' ? 'AI' : '-';

  return (
    <section className="session-strip">
      <div>
        <span>You</span>
        <strong>{heroTotal}</strong>
      </div>
      <div>
        <span>AI</span>
        <strong>{villainTotal}</strong>
      </div>
      <div>
        <span>Net</span>
        <strong>{net > 0 ? `+${net}` : net}</strong>
      </div>
      <div>
        <span>Leader</span>
        <strong>{leader}</strong>
      </div>
      <div>
        <span>Button</span>
        <strong>{button}</strong>
      </div>
      <div>
        <span>Blinds</span>
        <strong>
          {hand ? `${hand.small_blind}/${hand.big_blind}` : '-'}
        </strong>
      </div>
    </section>
  );
}
