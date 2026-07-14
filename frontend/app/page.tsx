'use client';

import ActionPanel from '@/components/ActionPanel';
import CoachPanel from '@/components/CoachPanel';
import HandHistory from '@/components/HandHistory';
import PokerTable from '@/components/PokerTable';
import { usePokerHand } from '@/hooks/usePokerHand';

export default function HomePage() {
  const {
    analysis,
    actionReview,
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
          <span className="status-pill">{hand?.street ?? 'not started'}</span>
          <button className="primary-button" onClick={startHand} disabled={isLoading}>
            New hand
          </button>
        </div>
      </section>

      {error ? (
        <div className="error-banner">
          <span>{error}</span>
          <button onClick={clearError}>Dismiss</button>
        </div>
      ) : null}

      <section className="game-layout">
        <div className="table-column">
          <PokerTable hand={hand} />
          <ActionPanel
            hand={hand}
            isLoading={isLoading}
            onAction={action}
            onAdvance={advance}
            onAnalyze={analyze}
            onStartHand={startHand}
          />
        </div>
        <aside className="side-column">
          <CoachPanel analysis={analysis} actionReview={actionReview} hand={hand} isLoading={isLoading} />
          <HandHistory hand={hand} />
        </aside>
      </section>
    </main>
  );
}
