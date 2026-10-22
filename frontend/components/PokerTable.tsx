'use client';

import { displayPlayer } from '@/i18n/translate';
import { useI18n } from '@/i18n/LanguageProvider';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';

import CardView from '@/components/CardView';
import type { HandAction, HandResult, HandState, Player, Street } from '@/types/poker';

interface TurnTimer { playerId: string; remaining: number; duration: number }

interface PokerTableProps {
  hand: HandState | null;
  seatCount: number;
  viewerId?: string;
  emptyStack?: number;
  turnTimer?: TurnTimer | null;
}

function Seat({
  player,
  active,
  timer,
  cardsHidden = false,
  dealer = false,
  startingStack = 1000,
  lastAction,
  label,
  slot,
}: {
  player?: Player;
  active: boolean;
  timer?: TurnTimer | null;
  cardsHidden?: boolean;
  dealer?: boolean;
  startingStack?: number;
  lastAction?: HandAction;
  label?: string;
  slot: string;
}) {
  const { t } = useI18n();
  const displayName = player ? displayPlayer(player, t) : t(label ?? 'Waiting');
  const displayPosition = player?.position ?? 'waiting';
  const shortPosition = ({ small_blind_button: 'SB', small_blind: 'SB', big_blind: 'BB', button: 'BTN', under_the_gun: 'UTG', hijack: 'HJ', cutoff: 'CO', waiting: '—' } as Record<string, string>)[displayPosition] ?? displayPosition;
  const displayStack = player?.stack ?? startingStack;
  const displayBet = player?.current_bet ?? 0;
  const status = player?.status ?? 'active';

  return (
    <div data-player-id={player?.id} className={`seat seat-${slot} ${active ? 'active-seat' : ''} ${timer ? 'timed-seat' : ''} ${timer && timer.remaining <= 10 ? 'seat-time-urgent' : ''} ${player ? '' : 'empty-seat'} ${cardsHidden ? 'concealed-seat' : ''} ${status === 'folded' ? 'folded-seat' : ''}`}>
      {dealer ? <span className="dealer-marker" aria-label={t("Button")}>D</span> : null}
      <div className="seat-bar">
        {timer ? <span className="seat-turn-timer" role="timer" aria-label={`${t("Time remaining")}: ${timer.remaining}`}><span aria-hidden="true">◷</span> {timer.remaining}<small>s</small></span> : null}
        <span className="seat-avatar" aria-hidden="true">{player ? displayName.slice(0, 1).toUpperCase() : "+"}</span>
        <div className="seat-info">
          <h2 title={displayName}>{displayName}</h2>
          <p title={t(displayPosition)}>{shortPosition}</p>
          {player ? (
            <span className={`action-badge action-${lastAction?.action ?? status}`}>
              {t(formatAction(lastAction, status))}
            </span>
          ) : (
            <span className="action-badge action-waiting">{t("Waiting")}</span>
          )}
        </div>
        <div className="seat-stats">
          <span className="seat-stack" aria-label={`${t("Stack")} ${displayStack}`}>{displayStack}</span>
        </div>
        {player ? <ChipStack amount={displayStack + displayBet} className="player-chip-stack" /> : null}
      </div>
      {displayBet > 0 ? <span className="seat-commitment" aria-label={`${t("Bet")} ${displayBet}`}>{displayBet}</span> : null}
      {player && status !== 'folded' ? (
        <div className="hole-cards">
          {Array.from({ length: 2 }, (_, index) => player.cards[index]).map((card, index) => (
            <CardView key={`${player.id}-${index}`} card={card} hidden={cardsHidden} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function PokerTable(props: PokerTableProps) {
  const key = `${props.hand?.hand_id}:${props.hand?.board.length}:${props.hand?.result?.reason ?? ''}`;
  return <TableScene key={key} {...props} />;
}

function TableScene({ hand, seatCount, viewerId = 'hero', emptyStack = 1000, turnTimer }: PokerTableProps) {
  const { t } = useI18n();
  const [displayedBoardCount, setDisplayedBoardCount] = useState(() =>
    hand ? (isAllInRunout(hand) ? runoutStages(hand)[0] ?? hand.board.length : hand.board.length) : 0,
  );
  const tableRef = useRef<HTMLDivElement>(null);
  const [flights, setFlights] = useState<{ id: string; amount: number; x: number; y: number; left: number; top: number }[]>([]);
  const revealVillainCards = hand?.result?.reason === 'showdown';
  const winnerBadge = winnerText(hand, t);
  const allInRunout = isAllInRunout(hand);
  const runoutComplete = !allInRunout || displayedBoardCount >= 5;
  const visibleBoard = useMemo(
    () => hand?.board.slice(0, displayedBoardCount) ?? [],
    [displayedBoardCount, hand?.board],
  );
  const seats = tableSeats(hand, seatCount, viewerId);


  useEffect(() => {
    if (!hand || !allInRunout) return;
    const stages = runoutStages(hand);
    const timers = stages.slice(1).map((count, index) =>
      window.setTimeout(() => setDisplayedBoardCount(count), 850 * (index + 1)),
    );

    return () => {
      timers.forEach(window.clearTimeout);
    };
  }, [hand, allInRunout]);

  useEffect(() => {
    if (!hand?.result || !runoutComplete) return;
    const timer = window.setTimeout(() => {
      const table = tableRef.current;
      const pot = table?.querySelector('.pot-display');
      if (!table || !pot) return;
      const origin = pot.getBoundingClientRect();
      const bounds = table.getBoundingClientRect();
      setFlights(hand.result!.player_results.filter(payout => payout.amount_won > 0).flatMap(payout => {
        const seat = Array.from(table.querySelectorAll<HTMLElement>('[data-player-id]')).find(item => item.dataset.playerId === payout.player_id);
        if (!seat) return [];
        const target = seat.getBoundingClientRect();
        return [{ id: payout.player_id, amount: payout.amount_won,
          left: origin.left + origin.width / 2 - bounds.left, top: origin.top + origin.height / 2 - bounds.top,
          x: target.left + target.width / 2 - origin.left - origin.width / 2,
          y: target.top + target.height / 2 - origin.top - origin.height / 2 }];
      }));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [hand, runoutComplete]);

  return (
    <section className={`table-surface classic-table ${hand?.result ? "has-result" : ""}`} aria-label={t("Poker table")}>
      <div ref={tableRef} className={`table-oval classic-oval table-seats-${seatCount} ${seatCount > 2 ? 'table-multiway' : ''}`}>
        {seats.map((seat) => (
          <Seat
            key={seat.slot}
            player={seat.player}
            startingStack={emptyStack}
            timer={seat.player?.id === turnTimer?.playerId && seat.player?.id !== viewerId && hand?.current_player_id === seat.player?.id && !hand?.result ? turnTimer : null}
            dealer={Boolean(seat.player && seat.player.id === hand?.dealer_player_id)}
            active={Boolean(seat.player && hand?.current_player_id === seat.player.id)}
            cardsHidden={Boolean(seat.player?.id !== viewerId && (!revealVillainCards || seat.player?.status === 'folded'))}
            lastAction={seat.player ? lastActionFor(hand, seat.player.id) : undefined}
            label={seat.label}
            slot={seat.slot}
          />
        ))}

        <div className="board-zone">
          <PotDisplay amount={hand?.pot ?? 0} />
          <div className="board-cards">
            {Array.from({ length: 5 }).map((_, index) => (
              <CardView key={`${hand?.hand_id ?? 'empty'}-${index}-${visibleBoard[index]?.rank ?? 'hidden'}`} card={visibleBoard[index]} hidden={!visibleBoard[index]} placeholder={!visibleBoard[index]} />
            ))}
          </div>
        </div>
        {flights.map(flight => <div key={flight.id} className="payout-flight" style={{ left: flight.left, top: flight.top, '--flight-x': `${flight.x}px`, '--flight-y': `${flight.y}px` } as CSSProperties} aria-hidden="true"><ChipStack amount={flight.amount} /><b>+{flight.amount}</b></div>)}
      </div>
      <div className={`showdown-slot ${allInRunout || (runoutComplete && (winnerBadge || hand?.result)) ? 'showdown-slot-visible' : ''}`}>
            {allInRunout && !runoutComplete ? <div className="runout-badge">{t("All-in runout")}</div> : null}
            {runoutComplete && (winnerBadge || hand?.result) ? (
              <>
                {winnerBadge ? <div className="winner-badge">{winnerBadge}</div> : null}
                {hand?.result ? <ShowdownSummary hand={hand} result={hand.result} /> : null}
              </>
            ) : null}
          </div>

    </section>
  );
}

function PotDisplay({ amount }: { amount: number }) {
  const { t } = useI18n();
  return (
    <div className="pot-display">
      <ChipStack amount={amount} />
      <span>{t("Pot")}</span>
      <strong>{amount}</strong>
    </div>
  );
}

function ChipStack({ amount, className = '' }: { amount: number; className?: string }) {
  const chips = chipCount(amount);
  if (chips === 0) {
    return null;
  }

  return (
    <div className={`chip-stack ${className}`} aria-hidden="true">
      {Array.from({ length: chips }).map((_, index) => (
        <span key={index} style={{ '--chip-index': index } as CSSProperties} />
      ))}
    </div>
  );
}

function chipCount(amount: number) {
  if (amount <= 0) {
    return 0;
  }
  if (amount < 100) {
    return 1;
  }
  if (amount < 500) {
    return 2;
  }
  if (amount < 1000) {
    return 3;
  }
  if (amount < 2000) {
    return 4;
  }
  return 5;
}

function tableSeats(hand: HandState | null, seatCount: number, viewerId = 'hero') {
  const slotsByCount: Record<number, string[]> = {
    2: ['bottom', 'top'],
    3: ['bottom', 'left', 'right'],
    4: ['bottom', 'left', 'top', 'right'],
    5: ['bottom', 'left', 'top-left', 'top-right', 'right'],
    6: ['bottom', 'left', 'top-left', 'top', 'top-right', 'right'],
  };
  const slots = slotsByCount[seatCount] ?? slotsByCount[2];
  const offset = Math.max(0, hand?.players.findIndex((player) => player.id === viewerId) ?? 0);
  return slots.map((slot, index) => ({ slot, player: hand?.players[(index + offset) % hand.players.length], label: `Seat ${index + 1}` }));
}

function ShowdownSummary({ hand, result }: { hand: HandState; result: HandResult }) {
  const { t } = useI18n();
  return (
    <div className="showdown-summary">
      {result.player_results.map((playerResult) => {
        const isWinner = result.winners.includes(playerResult.player_id);
        return (
          <div className={isWinner ? 'showdown-winner' : undefined} key={playerResult.player_id}>
            <span>{displayPlayer(hand.players.find(p => p.id === playerResult.player_id), t, playerResult.player_id)}</span>
            <strong>{t(label(playerResult.hand_strength?.category ?? playerResult.outcome))}</strong>
            {playerResult.amount_won ? <em>+{t(playerResult.amount_won)}</em> : null}
          </div>
        );
      })}
    </div>
  );
}

function lastActionFor(hand: HandState | null, playerId: string) {
  return hand?.history
    .slice()
    .reverse()
    .find((action) => action.player_id === playerId);
}

function formatAction(action: HandAction | undefined, status: Player['status']) {
  if (status === 'folded') {
    return 'folded';
  }
  if (status === 'all_in') {
    return 'all-in';
  }
  if (!action) {
    return 'waiting';
  }

  const actionLabel = action.action.replaceAll('_', ' ');
  return action.amount ? `${actionLabel} ${action.amount}` : actionLabel;
}

function winnerText(hand: HandState | null, t: <T>(value: T) => T) {
  const result = hand?.result;
  if (!result) {
    return null;
  }

  const winners = result.winners.map((winnerId) => displayPlayer(hand.players.find(p => p.id === winnerId), t, winnerId)).join(', ');
  const outcome = (result.pots?.length ?? 0) > 1 ? t('Pots awarded') : result.winners.length > 1 ? t('Split pot') : t('{0} wins').replace('{0}', winners);
  return `${outcome} ${result.pot_awarded}`;
}

function label(value: string) {
  return value.replaceAll('_', ' ');
}

function isAllInRunout(hand: HandState | null) {
  return Boolean(hand?.result && hand.notes.some((note) => note.toLowerCase().includes('all-in runout')));
}

function runoutStages(hand: HandState) {
  const start = boardCountBeforeRunout(lastVoluntaryAction(hand)?.street);
  return [start, 3, 4, 5].filter((count, index, counts) => (
    count <= hand.board.length && count >= start && counts.indexOf(count) === index
  ));
}

function boardCountBeforeRunout(street?: Street) {
  if (street === 'flop') {
    return 3;
  }
  if (street === 'turn') {
    return 4;
  }
  if (street === 'river' || street === 'showdown') {
    return 5;
  }
  return 0;
}

function lastVoluntaryAction(hand: HandState) {
  return hand.history
    .slice()
    .reverse()
    .find((action) => !['small_blind', 'big_blind'].includes(action.action));
}
