import CardView from '@/components/CardView';
import type { HandState, Player } from '@/types/poker';

interface PokerTableProps {
  hand: HandState | null;
}

function Seat({ player, active }: { player?: Player; active: boolean }) {
  return (
    <div className={`seat ${active ? 'active-seat' : ''}`}>
      <div>
        <h2>{player?.name ?? 'Waiting'}</h2>
        <p>{player?.position ?? 'seat'}</p>
      </div>
      <div className="seat-stats">
        <span>Stack {player?.stack ?? 0}</span>
        <span>Bet {player?.current_bet ?? 0}</span>
      </div>
      <div className="hole-cards">
        {(player?.cards ?? [undefined, undefined]).map((card, index) => (
          <CardView key={`${player?.id ?? 'empty'}-${index}`} card={card} hidden={!player} />
        ))}
      </div>
    </div>
  );
}

export default function PokerTable({ hand }: PokerTableProps) {
  const hero = hand?.players.find((player) => player.id === 'hero');
  const villain = hand?.players.find((player) => player.id === 'villain');

  return (
    <section className="table-surface">
      <Seat player={villain} active={hand?.current_player_id === 'villain'} />

      <div className="board-zone">
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

      <Seat player={hero} active={hand?.current_player_id === 'hero'} />
    </section>
  );
}

