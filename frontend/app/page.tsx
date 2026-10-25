'use client';

import ServerWakeLoader from '@/components/ServerWakeLoader';

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
  const [blindLevel, setBlindLevel] = useState<string | null>(null);
  const {
    analysis,
    solverModel,
    retrySolver,
    actionReview,
    decisionLog,
    error,
    hand,
    actionHand,
    isLoading,
    isAnalyzing,
    action,
    advance,
    clearError,
    startHand,
  } = usePokerHand();

  return (
    <main className="app-shell play-shell trainer-shell">
      <AppHeader>
          <div className="trainer-settings">
            <label className="seat-count-control trainer-setting"><span>{t('Players')}</span><select aria-label={t('Players')} value={hand && !hand.result ? hand.players.length : seatCount ?? hand?.players.length ?? 2} disabled={isLoading || Boolean(hand && !hand.result)} title={hand && !hand.result ? t('Change table settings between hands.') : undefined} onChange={(event) => setSeatCount(Number(event.target.value))}>
              {[2, 3, 4, 5, 6].map((count) => <option key={count} value={count}>{count}</option>)}
            </select></label>
            <label className="blind-level-control trainer-setting"><span>{t('Blinds')}</span><select aria-label={t('Blinds')} value={hand && !hand.result ? `${hand.small_blind}/${hand.big_blind}` : blindLevel ?? `${hand?.small_blind ?? 5}/${hand?.big_blind ?? 10}`} disabled={isLoading || Boolean(hand && !hand.result)} title={hand && !hand.result ? t('Change table settings between hands.') : undefined} onChange={event => setBlindLevel(event.target.value)}>
              {['1/2', '2/4', '5/10', '10/20', '25/50', '50/100'].map(level => <option key={level} value={level}>{level}</option>)}
            </select></label>
          </div>
      </AppHeader>
      <nav className="play-modes" aria-label={t('Game mode')}>
        <Link href="/" aria-current="page">{t('AI training')}</Link><Link href="/friends">{t('Play with friends')}</Link><Link href="/practice">{t('Practice')}</Link>
      </nav>
      <ServerWakeLoader active={Boolean(!hand && isLoading && !error)} />
      <div className="table-meta"><span>{t(hand?.street ?? 'not started')} · {hand?.players.length ?? 2} {t('players')}</span><span>{t('Blinds')} {hand?.small_blind ?? 5} / {hand?.big_blind ?? 10}</span></div>

      {error ? (
        <div className="error-banner" role="alert">
          <span>{t(error)}</span>
          <button onClick={clearError}>{t("Dismiss")}</button>
        </div>
      ) : null}

      <section className="game-layout">
        <div className="table-column">
          <PokerTable hand={hand} seatCount={hand?.players.length ?? 2} thinkingPlayerId={isLoading && !hand?.result && hand?.current_player_id !== 'hero' ? hand?.current_player_id : null} />
          <ActionPanel
            analysis={analysis}
            hand={actionHand}
            isLoading={isLoading}
            onAction={action}
            onAdvance={advance}
            tools={<><button aria-haspopup="dialog" onClick={() => setPanel('coach')}>{t('Coach')} ↑</button><button aria-haspopup="dialog" onClick={() => setPanel('history')}>{t('History')} ↑</button><button aria-haspopup="dialog" onClick={() => setPanel('session')}>{t('Session')} ↑</button></>}
            onStartHand={() => { const [small, big] = (blindLevel ?? `${hand?.small_blind ?? 5}/${hand?.big_blind ?? 10}`).split('/').map(Number); void startHand(seatCount ?? hand?.players.length ?? 2, { small_blind: small, big_blind: big }); }}
          />
        </div>
        <PanelSidebar active={panel} onClose={() => setPanel(null)} panels={[
          { id: 'coach', title: t('Coach'), content: <CoachPanel onRetrySolver={retrySolver} solverModel={solverModel} analysis={analysis} actionReview={actionReview} decisionLog={decisionLog} hand={hand} isLoading={isLoading || isAnalyzing} /> },
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
