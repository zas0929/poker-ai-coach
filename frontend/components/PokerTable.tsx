import CardView from '@/components/CardView';
import type { HandAction, HandResult, HandState, Player } from '@/types/poker';

interface PokerTableProps {
  hand: HandState | null;
}

function Seat({
  player,
  active,
  cardsHidden = false,
  lastAction,
}: {
  player?: Player;
  active: boolean;
  cardsHidden?: boolean;
  lastAction?: HandAction;
}) {
  return (
    <div className={`seat ${active ? 'active-seat' : ''}`}>
      <div>
        <h2>{player?.name ?? 'Waiting'}</h2>
        <p>{player?.position ?? 'seat'}</p>
        {player ? (
          <span className={`action-badge action-${lastAction?.action ?? player.status}`}>
            {formatAction(lastAction, player.status)}
          </span>
        ) : null}
      </div>
      <div className="seat-stats">
        <span>Stack {player?.stack ?? 0}</span>
        <span>Bet {player?.current_bet ?? 0}</span>
      </div>
      <div className="hole-cards">
        {(player?.cards ?? [undefined, undefined]).map((card, index) => (
          <CardView key={`${player?.id ?? 'empty'}-${index}`} card={card} hidden={!player || cardsHidden} />
        ))}
      </div>
      {cardsHidden ? <span className="hidden-card-label">Hidden until showdown</span> : null}
    </div>
  );
}

export default function PokerTable({ hand }: PokerTableProps) {
  const hero = hand?.players.find((player) => player.id === 'hero');
  const villain = hand?.players.find((player) => player.id === 'villain');
  const revealVillainCards = Boolean(hand?.result || hand?.street === 'showdown');
  const heroAction = lastActionFor(hand, 'hero');
  const villainAction = lastActionFor(hand, 'villain');
  const winnerBadge = winnerText(hand);

  return (
    <section className="table-surface">
      <Seat
        player={villain}
        active={hand?.current_player_id === 'villain'}
        cardsHidden={Boolean(villain) && !revealVillainCards}
        lastAction={villainAction}
      />

      <div className="board-zone">
        {winnerBadge ? <div className="winner-badge">{winnerBadge}</div> : null}
        {hand?.result ? <ShowdownSummary hand={hand} result={hand.result} /> : null}
        <div className="pot-display">
          <span>Pot</span>
          <strong>{hand?.pot ?? 0}</strong>
        </div>
        <div className="board-cards">
          {Array.from({ length: 5 }).map((_, index) => (
            <CardView key={index} card={hand?.board[index]} hidden={!hand?.board[index]} />
          ))}
        </div>
      </div>

      <Seat player={hero} active={hand?.current_player_id === 'hero'} lastAction={heroAction} />
    </section>
  );
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

function label(value: string) {
  return value.replaceAll('_', ' ');
}
