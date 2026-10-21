'use client';

import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';

import CardView from '@/components/CardView';
import type { HandAction, HandResult, HandState, Player, Street } from '@/types/poker';

interface PokerTableProps {
  hand: HandState | null;
  seatCount: number;
}

function Seat({
  player,
  active,
  cardsHidden = false,
  lastAction,
  label,
  slot,
}: {
  player?: Player;
  active: boolean;
  cardsHidden?: boolean;
  lastAction?: HandAction;
  label?: string;
  slot: string;
}) {
  const displayName = player?.name ?? label ?? 'Waiting';
  const displayPosition = player?.position ?? 'waiting';
  const displayStack = player?.stack ?? 1000;
  const displayBet = player?.current_bet ?? 0;
  const status = player?.status ?? 'active';

  return (
    <div className={`seat seat-${slot} ${active ? 'active-seat' : ''} ${player ? '' : 'empty-seat'}`}>
      <div className="seat-bar">
        <div className="seat-info">
          <h2>{displayName}</h2>
          <p>{displayPosition}</p>
          {player ? (
            <span className={`action-badge action-${lastAction?.action ?? status}`}>
              {formatAction(lastAction, status)}
            </span>
          ) : (
            <span className="action-badge action-waiting">Waiting</span>
          )}
        </div>
        <div className="seat-stats">
          <span>Stack {displayStack}</span>
          <span>Bet {displayBet}</span>
        </div>
        {player ? <ChipStack amount={displayStack + displayBet} className="player-chip-stack" /> : null}
      </div>
      {player ? (
        <div className="hole-cards">
          {player.cards.map((card, index) => (
            <CardView key={`${player.id}-${index}`} card={card} hidden={cardsHidden} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function PokerTable({ hand, seatCount }: PokerTableProps) {
  const [displayedBoardCount, setDisplayedBoardCount] = useState(0);
  const [showChipFlight, setShowChipFlight] = useState(false);
  const revealVillainCards = Boolean(hand?.result || hand?.street === 'showdown');
  const heroAction = lastActionFor(hand, 'hero');
  const villainAction = lastActionFor(hand, 'villain');
  const winnerBadge = winnerText(hand);
  const allInRunout = isAllInRunout(hand);
  const runoutComplete = !allInRunout || displayedBoardCount >= 5;
  const visibleBoard = useMemo(
    () => hand?.board.slice(0, displayedBoardCount) ?? [],
    [displayedBoardCount, hand?.board],
  );
  const seats = tableSeats(hand, seatCount);
  const winnerSlot = winnerSeatSlot(hand);

  useEffect(() => {
    setShowChipFlight(false);

    if (!hand) {
      setDisplayedBoardCount(0);
      return;
    }

    if (!isAllInRunout(hand)) {
      setDisplayedBoardCount(hand.board.length);
      return;
    }

    const stages = runoutStages(hand);
    setDisplayedBoardCount(stages[0] ?? hand.board.length);
    const timers = stages.slice(1).map((count, index) =>
      window.setTimeout(() => setDisplayedBoardCount(count), 850 * (index + 1)),
    );

    return () => {
      timers.forEach(window.clearTimeout);
    };
  }, [hand]);

  useEffect(() => {
    setShowChipFlight(false);

    if (!winnerSlot || !runoutComplete) {
      return;
    }

    const timer = window.setTimeout(() => setShowChipFlight(true), 1000);
    return () => window.clearTimeout(timer);
  }, [hand?.hand_id, runoutComplete, winnerSlot]);

  return (
    <section className="table-surface">
      <div className="table-oval">
        {seats.map((seat) => (
          <Seat
            key={seat.slot}
            player={seat.player}
            active={Boolean(seat.player && hand?.current_player_id === seat.player.id)}
            cardsHidden={Boolean(seat.player?.id === 'villain' && !revealVillainCards)}
            lastAction={seat.player?.id === 'hero' ? heroAction : seat.player?.id === 'villain' ? villainAction : undefined}
            label={seat.label}
            slot={seat.slot}
          />
        ))}

        <div className="board-zone">
          <div className={`showdown-slot ${allInRunout || (runoutComplete && (winnerBadge || hand?.result)) ? 'showdown-slot-visible' : ''}`}>
            {allInRunout && !runoutComplete ? <div className="runout-badge">All-in runout</div> : null}
            {runoutComplete && (winnerBadge || hand?.result) ? (
              <>
                {winnerBadge ? <div className="winner-badge">{winnerBadge}</div> : null}
                {hand?.result ? <ShowdownSummary hand={hand} result={hand.result} /> : null}
              </>
            ) : null}
          </div>
          <PotDisplay amount={hand?.pot ?? 0} />
          <div className="board-cards">
            {Array.from({ length: 5 }).map((_, index) => (
              <CardView key={`${hand?.hand_id ?? 'empty'}-${index}-${visibleBoard[index]?.rank ?? 'hidden'}`} card={visibleBoard[index]} hidden={!visibleBoard[index]} />
            ))}
          </div>
        </div>
        {showChipFlight && winnerSlot ? <ChipFlight target={winnerSlot} /> : null}
      </div>
    </section>
  );
}

function PotDisplay({ amount }: { amount: number }) {
  return (
    <div className="pot-display">
      <ChipStack amount={amount} />
      <span>Pot</span>
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

function ChipFlight({ target }: { target: string }) {
  return (
    <div className={`chip-flight chip-flight-${target}`} aria-hidden="true">
      <span />
      <span />
      <span />
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

function tableSeats(hand: HandState | null, seatCount: number) {
  const hero = hand?.players.find((player) => player.id === 'hero');
  const villain = hand?.players.find((player) => player.id === 'villain');
  const slotsByCount: Record<number, string[]> = {
    2: ['top', 'bottom'],
    3: ['top', 'right', 'bottom'],
    4: ['top', 'right', 'bottom', 'left'],
    5: ['top', 'top-right', 'right', 'bottom', 'left'],
    6: ['top', 'top-right', 'right', 'bottom', 'left', 'top-left'],
  };
  const slots = slotsByCount[seatCount] ?? slotsByCount[2];

  return slots.map((slot, index) => {
    if (slot === 'top') {
      return { slot, player: villain, label: 'AI Opponent' };
    }
    if (slot === 'bottom') {
      return { slot, player: hero, label: 'You' };
    }
    return { slot, player: undefined, label: `Player ${index + 1}` };
  });
}

function ShowdownSummary({ hand, result }: { hand: HandState; result: HandResult }) {
  return (
    <div className="showdown-summary">
      {result.player_results.map((playerResult) => {
        const isWinner = result.winners.includes(playerResult.player_id);
        return (
          <div className={isWinner ? 'showdown-winner' : undefined} key={playerResult.player_id}>
            <span>{playerName(hand, playerResult.player_id)}</span>
            <strong>{label(playerResult.hand_strength?.category ?? playerResult.outcome)}</strong>
            {playerResult.amount_won ? <em>+{playerResult.amount_won}</em> : null}
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

function winnerText(hand: HandState | null) {
  const result = hand?.result;
  if (!result) {
    return null;
  }

  const winners = result.winners.map((winnerId) => playerName(hand, winnerId)).join(', ');
  const outcome = result.winners.length > 1 ? 'Split pot' : `${winners} wins`;
  return `${outcome} ${result.pot_awarded}`;
}

function playerName(hand: HandState, playerId: string) {
  return hand.players.find((player) => player.id === playerId)?.name ?? playerId;
}

function winnerSeatSlot(hand: HandState | null) {
  const winner = hand?.result?.winners[0];
  if (winner === 'hero') {
    return 'bottom';
  }
  if (winner === 'villain') {
    return 'top';
  }
  return null;
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
