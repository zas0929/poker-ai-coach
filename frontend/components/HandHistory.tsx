import type { HandState } from '@/types/poker';

interface HandHistoryProps {
  hand: HandState | null;
}

export default function HandHistory({ hand }: HandHistoryProps) {
  return (
    <section className="history-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Hand Log</p>
          <h2>Actions</h2>
        </div>
      </div>

      <ol className="history-list">
        {(hand?.history ?? []).map((action, index) => (
          <li key={`${action.player_id}-${action.action}-${index}`}>
            <span>{action.street}</span>
            <strong>{hand?.players.find((p) => p.id === action.player_id)?.name ?? action.player_id}</strong>
            <em>
              {action.action}
              {action.amount ? ` ${action.amount}` : ''}
            </em>
          </li>
        ))}
      </ol>
    </section>
  );
}

