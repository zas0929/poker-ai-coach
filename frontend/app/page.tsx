'use client';

import { displayPlayer } from '@/i18n/translate';
import { useI18n } from '@/i18n/LanguageProvider';

import { useState } from 'react';
import Link from 'next/link';
import AppHeader from '@/components/AppHeader';

import ActionPanel from '@/components/ActionPanel';
import CoachPanel from '@/components/CoachPanel';
import HandHistory from '@/components/HandHistory';
import PokerTable from '@/components/PokerTable';
import PanelSidebar from '@/components/PanelSidebar';
import { usePokerHand } from '@/hooks/usePokerHand';

export default function HomePage() {
  const { t } = useI18n();
  const [panel, setPanel] = useState<string | null>(null);
  const [seatCount, setSeatCount] = useState<number | null>(null);
  const {
    analysis,
    actionReview,
    decisionLog,
    error,
    hand,
    isLoading,
    isAnalyzing,
    action,
    advance,
    analyze,
    clearError,
    startHand,
  } = usePokerHand();

  return (
    <main className="app-shell play-shell">
      <AppHeader>
          <label className="seat-count-control"><span>{t('Players')}</span><select aria-label={t('Players')} value={seatCount ?? hand?.players.length ?? 2} disabled={isLoading || Boolean(hand && !hand.result)} onChange={(event) => setSeatCount(Number(event.target.value))}>
            {[2, 3, 4, 5, 6].map((count) => <option key={count} value={count}>{count}</option>)}
          </select></label>
      </AppHeader>
      <nav className="play-modes" aria-label={t('Game mode')}>
        <Link href="/" aria-current="page">{t('AI training')}</Link><Link href="/friends">{t('Play with friends')}</Link><Link href="/practice">{t('Practice')}</Link>
      </nav>
      <div className="table-meta"><span>{t(hand?.street ?? 'not started')} · {hand?.players.length ?? 2} {t('players')}</span><span>{t('Blinds')} {hand?.small_blind ?? 5} / {hand?.big_blind ?? 10}</span></div>

      {error ? (
        <div className="error-banner" role="alert">
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
            tools={<><button aria-haspopup="dialog" onClick={() => setPanel('coach')}>{t('Coach')} ↑</button><button aria-haspopup="dialog" onClick={() => setPanel('history')}>{t('History')} ↑</button><button aria-haspopup="dialog" onClick={() => setPanel('session')}>{t('Session')} ↑</button></>}
            onStartHand={() => startHand(seatCount ?? hand?.players.length ?? 2)}
          />
        </div>
        <PanelSidebar active={panel} onClose={() => setPanel(null)} panels={[
          { id: 'coach', title: t('Coach'), content: <CoachPanel analysis={analysis} actionReview={actionReview} decisionLog={decisionLog} hand={hand} isLoading={isLoading || isAnalyzing} /> },
          { id: 'history', title: t('History'), content: <HandHistory hand={hand} /> },
          { id: 'session', title: t('Session'), content: <section className="control-panel session-panel"><h2>{t('Session')}</h2><SessionStrip hand={hand} /><Link className="mode-link" href="/practice">{t('Practice & decisions')} →</Link></section> },
        ]} />
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
