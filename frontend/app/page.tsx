'use client';

import { displayPlayer } from '@/i18n/translate';
import { useI18n } from '@/i18n/LanguageProvider';

import { useState } from 'react';
import Link from 'next/link';

import ActionPanel from '@/components/ActionPanel';
import CoachPanel from '@/components/CoachPanel';
import HandHistory from '@/components/HandHistory';
import PokerTable from '@/components/PokerTable';
import { usePokerHand } from '@/hooks/usePokerHand';

export default function HomePage() {
  const { t } = useI18n();
  const [seatCount, setSeatCount] = useState<number | null>(null);
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
          <p className="eyebrow">{t("Texas Hold'em AI Coach")}</p>
          <h1>{t("Poker AI Coach")}</h1>
        </div>
        <div className="status-row">
          <Link className="mode-link" href="/practice">{t("Practice & decisions")}</Link>
          <Link className="mode-link" href="/friends">{t("Play with friends")}</Link>
          <label className="seat-count-control">
            <span>{t("Seats")}</span>
            <select value={seatCount ?? hand?.players.length ?? 2} disabled={isLoading || Boolean(hand && !hand.result)} onChange={(event) => setSeatCount(Number(event.target.value))}>
              {[2, 3, 4, 5, 6].map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </label>
          <span className="status-pill">{t(hand?.street ?? 'not started')}</span>
          <button className="primary-button" onClick={() => startHand(seatCount ?? hand?.players.length ?? 2)} disabled={isLoading || Boolean(hand && !hand.result)}>{t("New hand")}</button>
        </div>
      </section>

      <SessionStrip hand={hand} />

      {error ? (
        <div className="error-banner">
          <span>{t(error)}</span>
          <button onClick={clearError}>{t("Dismiss")}</button>
        </div>
      ) : null}

      <section className="game-layout">
        <div className="table-column">
          <PokerTable hand={hand} seatCount={hand?.players.length ?? 2} />
          <ActionPanel
            analysis={analysis}
            hand={hand}
            isLoading={isLoading}
            onAction={action}
            onAdvance={advance}
            onAnalyze={analyze}
            onStartHand={() => startHand(seatCount ?? hand?.players.length ?? 2)}
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
  const { t } = useI18n();
  const hero = hand?.players.find((player) => player.id === 'hero');
  const opponents = hand?.players.filter((player) => player.id !== 'hero') ?? [];
  const heroTotal = (hero?.stack ?? 0) + (hero?.current_bet ?? 0);
  const aiTotal = opponents.reduce((sum, p) => sum + p.stack + p.current_bet, 0);
  const net = heroTotal - 1000;
  const leader = hand?.players.reduce((best, p) => p.stack > best.stack ? p : best, hand.players[0]);
  const button = displayPlayer(hand?.players.find((p) => p.id === hand.dealer_player_id), t);
  return (
    <section className="session-strip">
      <div><span>{t("You")}</span><strong>{heroTotal}</strong></div>
      <div><span>{t(opponents.length)}{t(" AI players")}</span><strong>{aiTotal}</strong></div>
      <div><span>{t("From initial stack")}</span><strong>{t(net > 0 ? `+${net}` : net)}</strong></div>
      <div><span>{t("Largest stack")}</span><strong>{displayPlayer(leader, t)}</strong></div>
      <div><span>{t("Button")}</span><strong>{button}</strong></div>
      <div><span>{t("Blinds")}</span><strong>{t(hand ? `${hand.small_blind}/${hand.big_blind}` : '-')}</strong></div>
    </section>
  );
}
