import type { ActionReview, HandAnalysis, HandState } from '@/types/poker';

interface CoachPanelProps {
  analysis: HandAnalysis | null;
  actionReview: ActionReview | null;
  decisionLog: ActionReview[];
  hand: HandState | null;
  isLoading: boolean;
}

function percent(value?: number) {
  return `${Math.round((value ?? 0) * 1000) / 10}%`;
}

function label(value?: string) {
  return value?.replaceAll('_', ' ') ?? '-';
}

export default function CoachPanel({
  analysis,
  actionReview,
  decisionLog,
  hand,
  isLoading,
}: CoachPanelProps) {
  const result = hand?.result;
  const decisionStats = decisionLog.reduce(
    (stats, review) => ({
      ...stats,
      [review.verdict]: stats[review.verdict] + 1,
      total: stats.total + 1,
    }),
    { acceptable: 0, optimal: 0, reconsider: 0, total: 0 },
  );

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
        <div>
          <span>Preflop</span>
          <strong>{analysis?.preflop_profile.notation ?? '-'}</strong>
        </div>
      </div>

      {analysis ? (
        <div className="coach-summary">
          <p>{analysis.coach_summary}</p>
          <div className="summary-meta">
            <span>Confidence {percent(analysis.confidence)}</span>
            <span>Risk {label(analysis.risk_level)}</span>
            <span>{label(analysis.preflop_profile.category)}</span>
          </div>
          {analysis.preflop_profile.tags.length ? (
            <div className="tag-row">
              {analysis.preflop_profile.tags.map((tag) => (
                <span key={tag}>{label(tag)}</span>
              ))}
            </div>
          ) : null}
          {analysis.draw_profile.draws.length ? (
            <div className="draw-box">
              <strong>{analysis.draw_profile.outs} estimated outs</strong>
              <span>{analysis.draw_profile.draws.map(label).join(', ')}</span>
            </div>
          ) : null}
          <ul>
            {analysis.key_factors.map((factor) => (
              <li key={factor}>{factor}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {actionReview ? (
        <div className={`action-review review-${actionReview.verdict}`}>
          <div className="review-heading">
            <span>Last decision</span>
            <strong>{label(actionReview.verdict)}</strong>
          </div>
          <p>{actionReview.summary}</p>
          <div className="summary-meta">
            <span>Chosen {label(actionReview.chosen_action)}</span>
            <span>Recommended {label(actionReview.recommended_action)}</span>
          </div>
        </div>
      ) : null}

      {decisionLog.length ? (
        <div className="decision-log-panel">
          <div className="review-heading">
            <span>Session decisions</span>
            <strong>{decisionStats.total}</strong>
          </div>
          <div className="decision-stats">
            <span>Optimal {decisionStats.optimal}</span>
            <span>Acceptable {decisionStats.acceptable}</span>
            <span>Review {decisionStats.reconsider}</span>
          </div>
          <ol>
            {decisionLog.slice(0, 5).map((review, index) => (
              <li key={`${review.hand_id}-${review.street}-${index}`}>
                <span>{label(review.street)}</span>
                <strong>{label(review.verdict)}</strong>
                <em>
                  {label(review.chosen_action)} vs {label(review.recommended_action)}
                </em>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

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
