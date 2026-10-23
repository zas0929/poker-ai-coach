'use client';

import { displayPlayer } from '@/i18n/translate';
import { useI18n } from '@/i18n/LanguageProvider';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';

import { useTableSound } from '@/components/TableSoundProvider';
import { newActionSounds } from '@/services/tableSounds';
import { chipBreakdown } from '@/services/chips';
import CardView from '@/components/CardView';
import type { HandAction, HandState, Player, Street } from '@/types/poker';

interface TurnTimer { playerId: string; remaining: number; duration: number }

interface PokerTableProps {
  hand: HandState | null;
  seatCount: number;
  viewerId?: string;
  emptyStack?: number;
  turnTimer?: TurnTimer | null;
  silent?: boolean;
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
      </div>
      {player ? (
        <div className="seat-hand">
          <div className="hole-cards" aria-hidden={status === 'folded' || undefined}>
            {status !== 'folded' ? Array.from({ length: 2 }, (_, index) => player.cards[index]).map((card, index) => (
              <CardView key={`${player.id}-${index}`} card={card} hidden={cardsHidden} />
            )) : null}
          </div>
          <div className="seat-money">
            <ChipStack amount={displayStack} className="player-chip-cluster" />
            {player.current_bet > 0 ? <span className="table-bet" aria-label={`${t('Bet')} ${player.current_bet}`}>
              <b>{player.current_bet}</b><ChipStack amount={player.current_bet} className="bet-chip-stack" />
            </span> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function PokerTable(props: PokerTableProps) {
  const { play, ready } = useTableSound();
  const lastDeal = useRef<{ id: string; board: number } | null>(null);
  const lastTimer = useRef('');
  const lastSoundHand = useRef<HandState | null>(null);
  useEffect(() => {
    const hand = props.hand;
    if (!hand || props.silent || !ready) return;
    const previous = lastDeal.current;
    if (previous?.id !== hand.hand_id && !hand.result) play('deal', hand.players.length * 2);
    const events = newActionSounds(lastSoundHand.current, hand);
    for (const kind of ['check', 'chips'] as const) {
      const count = events.filter(event => event === kind).length;
      if (count) play(kind, count);
    }
    lastSoundHand.current = hand;
    lastDeal.current = { id: hand.hand_id, board: hand.board.length };
  }, [props.hand, props.silent, play, ready]);
  useEffect(() => {
    const hand = props.hand;
    if (!hand || hand.result || !props.turnTimer || props.silent || !ready) return;
    const turn = `${hand.hand_id}:${hand.history.length}:${props.turnTimer.playerId}`;
    if (lastTimer.current !== turn) { play('timer'); lastTimer.current = turn; }
  }, [props.hand, props.turnTimer, props.silent, play, ready]);
  const key = props.hand?.hand_id ?? 'empty';
  return <TableScene key={key} {...props} />;
}

function TableScene({ hand, seatCount, viewerId = 'hero', emptyStack = 1000, turnTimer, silent = false }: PokerTableProps) {
  const { t } = useI18n();
  const { play } = useTableSound();
  const previousBoard = useRef(hand && isAllInRunout(hand) ? runoutStages(hand)[0] ?? hand.board.length : hand?.board.length ?? 0);
  const [displayedBoardCount, setDisplayedBoardCount] = useState(() =>
    hand ? (isAllInRunout(hand) ? runoutStages(hand)[0] ?? hand.board.length : hand.board.length) : 0,
  );
  const tableRef = useRef<HTMLDivElement>(null);
  const [flights, setFlights] = useState<{ id: string; amount: number; x: number; y: number; left: number; top: number }[]>([]);
  const [potTransferred, setPotTransferred] = useState(false);
  const revealVillainCards = hand?.result?.reason === 'showdown';
  const winnerBadge = winnerText(hand, t);
  const allInRunout = isAllInRunout(hand);
  const runoutSchedule = allInRunout && hand ? runoutStages(hand).join(',') : '';
  const boardCount = allInRunout
    ? Math.max(Number(runoutSchedule.split(',')[0]), displayedBoardCount)
    : hand?.board.length ?? 0;
  const runoutComplete = !allInRunout || boardCount >= 5;
  const visibleBoard = useMemo(
    () => hand?.board.slice(0, boardCount) ?? [],
    [boardCount, hand?.board],
  );
  const seats = tableSeats(hand, seatCount, viewerId);
  useEffect(() => {
    if (!silent && boardCount > previousBoard.current) play('reveal', boardCount - previousBoard.current);
    previousBoard.current = boardCount;
  }, [boardCount, play, silent]);


  useEffect(() => {
    if (!runoutSchedule) return;
    const stages = runoutSchedule.split(',').map(Number);
    const timers = stages.slice(1).map((count, index) =>
      window.setTimeout(() => setDisplayedBoardCount(count), 850 * (index + 1)),
    );

    return () => {
      timers.forEach(window.clearTimeout);
    };
  }, [runoutSchedule]);

  useEffect(() => {
    if (!hand?.result || !runoutComplete || potTransferred) return;
    let completionTimer: number | undefined;
    const timer = window.setTimeout(() => {
      const table = tableRef.current;
      const pot = table?.querySelector('.pot-display');
      if (!table || !pot) return;
      const origin = pot.getBoundingClientRect();
      const bounds = table.getBoundingClientRect();
      if (!silent) play('win');
      setFlights(hand.result!.player_results.filter(payout => payout.amount_won > 0).flatMap(payout => {
        const seat = Array.from(table.querySelectorAll<HTMLElement>('[data-player-id]')).find(item => item.dataset.playerId === payout.player_id);
        if (!seat) return [];
        const target = seat.getBoundingClientRect();
        return [{ id: payout.player_id, amount: payout.amount_won,
          left: origin.left + origin.width / 2 - bounds.left, top: origin.top + origin.height / 2 - bounds.top,
          x: target.left + target.width / 2 - origin.left - origin.width / 2,
          y: target.top + target.height / 2 - origin.top - origin.height / 2 }];
      }));
      // Match the one-second payout flight, including when reduced motion hides it.
      completionTimer = window.setTimeout(() => {
        setPotTransferred(true);
        setFlights([]);
      }, 1000);
    }, 1000);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(completionTimer);
    };
  }, [hand, runoutComplete, potTransferred, play, silent]);

  return (
    <section className={`table-surface classic-table ${hand?.result ? "has-result" : ""}`} aria-label={t("Poker table")}>
      <div ref={tableRef} className={`table-oval classic-oval table-seats-${seatCount} ${seatCount > 2 ? 'table-multiway' : ''}`}>
        {seats.map((seat) => (
          <Seat
            key={seat.slot}
            player={seat.player}
            startingStack={emptyStack}
            timer={seat.player?.id === turnTimer?.playerId && hand?.current_player_id === seat.player?.id && !hand?.result ? turnTimer : null}
            dealer={Boolean(seat.player && seat.player.id === hand?.dealer_player_id)}
            active={Boolean(seat.player && hand?.current_player_id === seat.player.id)}
            cardsHidden={Boolean(seat.player?.id !== viewerId && (!revealVillainCards || seat.player?.status === 'folded'))}
            lastAction={seat.player ? lastActionFor(hand, seat.player.id) : undefined}
            label={seat.label}
            slot={seat.slot}
          />
        ))}

        <div className="board-zone">
          <PotDisplay amount={potTransferred ? 0 : hand?.result?.pot_awarded ?? hand?.pot ?? 0} />
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
                {winnerBadge ? <div className="winner-badge" role="status"><strong>{winnerBadge}</strong>
                  {hand?.result?.player_results.filter(player => hand.result!.winners.includes(player.player_id)).map(player => (
                    <span className="winning-hand" key={player.player_id}>
                      {hand.result!.winners.length > 1 ? `${displayPlayer(hand.players.find(item => item.id === player.player_id), t, player.player_id)}: ` : ''}
                      {player.hand_strength ? t(label(player.hand_strength.category)) : t('Everyone else folded')}
                      {hand.result!.winners.length > 1 ? ` · +${player.amount_won}` : ''}
                    </span>
                  ))}
                </div> : null}
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
  const { t } = useI18n();
  const piles = chipBreakdown(amount);
  if (!piles.length) return null;
  const physicalPiles = piles.flatMap(pile => Array.from({ length: Math.ceil(pile.count / 10) }, (_, pileIndex) => ({ ...pile, count: Math.min(10, pile.count - pileIndex * 10), pileIndex })));
  const clustered = className.includes('player-chip-cluster');
  // Concentric groups keep each denomination separate, including unusually large stacks.
  const positions = physicalPiles.map((_, index) => {
    if (physicalPiles.length <= 6) {
      const radius = [0, 0, 12, 15, 17, 21, 23][physicalPiles.length];
      const angle = -Math.PI / 2 + index * Math.PI * 2 / physicalPiles.length;
      return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius * .85 };
    }
    if (index === 0) return { x: 0, y: 0 };
    let ring = 1, slot = index - 1;
    while (slot >= ring * 6) { slot -= ring * 6; ring++; }
    const angle = -Math.PI / 2 + slot * Math.PI * 2 / (ring * 6);
    return { x: Math.cos(angle) * ring * 24, y: Math.sin(angle) * ring * 21 };
  });
  const radiusX = Math.max(...positions.map(p => Math.abs(p.x)));
  const radiusY = Math.max(...positions.map(p => Math.abs(p.y)));
  const clusterStyle = clustered ? { '--cluster-width': radiusX * 2 + 20, '--cluster-height': radiusY * 2 + 29, '--cluster-base': radiusY } as CSSProperties : undefined;
  return <div className={`denomination-stack ${className}`} style={clusterStyle} role="img" aria-label={`${t('Chips')}: ${amount}`}>
    {physicalPiles.map((pile, index) => {
      const count = pile.count;
      return <div className="chip-pile" key={`${pile.value}-${pile.pileIndex}`} style={{ '--chip-color': pile.color, '--chip-ink': pile.ink, '--pile-count': count, ...(clustered ? { '--pile-x': positions[index].x, '--pile-y': positions[index].y, zIndex: Math.round(positions[index].y + radiusY) } : {}) } as CSSProperties}>
        {Array.from({ length: count }, (_, index) => <span className="denomination-chip" key={index} style={{ '--chip-index': index } as CSSProperties}>
          {index === count - 1 ? <i>{pile.value >= 1000 ? `${pile.value / 1000}k` : pile.value}</i> : null}
        </span>)}
      </div>;
    })}
  </div>;
}

function tableSeats(hand: HandState | null, seatCount: number, viewerId = 'hero') {
  const slotsByCount: Record<number, string[]> = {
    2: ['bottom', 'top'],
    3: ['bottom', 'left', 'right'],
    4: ['bottom', 'top-left', 'top', 'top-right'],
    5: ['bottom', 'left', 'top-left', 'top-right', 'right'],
    6: ['bottom', 'left', 'top-left', 'top', 'top-right', 'right'],
  };
  const slots = slotsByCount[seatCount] ?? slotsByCount[2];
  const offset = Math.max(0, hand?.players.findIndex((player) => player.id === viewerId) ?? 0);
  return slots.map((slot, index) => ({ slot, player: hand?.players[(index + offset) % hand.players.length], label: `Seat ${index + 1}` }));
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
  const trainerWinner = result.winners.length === 1 && hand.players.some(player => player.id === result.winners[0] && player.id === 'hero' && player.name === 'You');
  const outcome = (result.pots?.length ?? 0) > 1 ? t('Pots awarded') : result.winners.length > 1 ? t('Split pot') : trainerWinner ? t('You win') : t('{0} wins').replace('{0}', winners);
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
