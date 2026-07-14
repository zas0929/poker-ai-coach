import type { HandAnalysis, HandState } from '@/types/poker';

interface CoachPanelProps {
  analysis: HandAnalysis | null;
  hand: HandState | null;
  isLoading: boolean;
}

function percent(value?: number) {
  return `${Math.round((value ?? 0) * 1000) / 10}%`;
}

function label(value?: string) {
  return value?.replaceAll('_', ' ') ?? '-';
}

export default function CoachPanel({ analysis, hand, isLoading }: CoachPanelProps) {
  const result = hand?.result;

  return (
    <section className="coach-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Coach Panel</p>
          <h2>{analysis?.recommended_action ?? 'waiting'}</h2>
        </div>
        <span className="status-pill">{isLoading ? 'thinking' : hand?.street ?? 'idle'}</span>
      </div>

      <div className="metric-grid">
        <div>
          <span>Equity</span>
          <strong>{percent(analysis?.equity)}</strong>
        </div>
        <div>
          <span>Required</span>
          <strong>{percent(analysis?.required_equity)}</strong>
        </div>
        <div>
          <span>EV call</span>
          <strong>{analysis?.ev_call ?? 0}</strong>
        </div>
        <div>
          <span>Hand</span>
          <strong>{label(analysis?.hand_strength.category)}</strong>
        </div>
      </div>

      {result ? (
        <div className="result-panel">
          <div>
            <span>Result</span>
            <strong>{label(result.reason)}</strong>
          </div>
          <div>
            <span>Winner</span>
            <strong>{result.winners.join(', ')}</strong>
          </div>
          <div>
            <span>Pot awarded</span>
            <strong>{result.pot_awarded}</strong>
          </div>
          <div className="result-list">
            {result.player_results.map((player) => (
              <p key={player.player_id}>
                <strong>{player.player_id}</strong>
                <span>
                  {label(player.outcome)}
                  {player.hand_strength ? ` · ${label(player.hand_strength.category)}` : ''}
                  {player.amount_won ? ` · +${player.amount_won}` : ''}
                </span>
              </p>
            ))}
          </div>
        </div>
      ) : null}

      <div className="coach-notes">
        {(analysis?.notes.length ? analysis.notes : ['Start a hand to get live decision analysis.']).map((note) => (
          <p key={note}>{note}</p>
        ))}
      </div>
    </section>
  );
}
