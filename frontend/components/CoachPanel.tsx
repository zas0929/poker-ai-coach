'use client';


import TrainerSolverPanel from '@/components/TrainerSolverPanel';
import type { TrainerModel } from '@/services/trainerSolver';
import InfoTip from '@/components/InfoTip';
import { displayPlayer } from '@/i18n/translate';
import { useI18n } from '@/i18n/LanguageProvider';
import type { ActionReview, HandAnalysis, HandState } from '@/types/poker';

interface CoachPanelProps {
  solverModel?: TrainerModel | null;
  onRetrySolver?: () => void;
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
  if (value === 'optimal') return 'matches coach';
  return value?.replaceAll('_', ' ') ?? '-';
}

export default function CoachPanel({
  solverModel = null,
  onRetrySolver,
  analysis,
  actionReview,
  decisionLog,
  hand,
  isLoading,
}: CoachPanelProps) {
  const { t } = useI18n();
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
          <p className="eyebrow">{t("Coach Panel")}</p>
          <h2>{t(analysis?.recommended_action === 'raise' ? 'Raise to' : analysis?.recommended_action ?? (result ? 'hand complete' : isLoading ? 'thinking' : 'waiting'))}{analysis?.recommended_amount != null ? ` ${analysis.recommended_amount}` : ''}</h2>
        </div>
        <span className="status-pill">{t(isLoading ? 'thinking' : hand?.street ?? 'idle')}</span>
      </div>

      <p className="range-detail">{t("Current advice: equity and betting heuristics.")}</p>
      <TrainerSolverPanel result={solverModel} hand={hand} analysis={analysis} onRetry={onRetrySolver} />
      <div className="metric-grid">
        <div className="coach-metric">
          <InfoTip label="Equity" explanation="Equity estimates your share of the pot against assumed opponent ranges. It includes split pots and is not a guarantee." />
          <strong>{t(analysis ? percent(analysis.equity) : '—')}</strong>
        </div>
        <div className="coach-metric">
          <InfoTip label={analysis?.call_ev_available === false ? 'Price proxy' : 'Required'} explanation="The call threshold is call / (pot + call). In multiway pots the displayed proxy is approximate: side pots and eligibility matter." />
          <strong>{t(analysis ? percent(analysis.required_equity) : '—')}</strong>
        </div>
        <div className="coach-metric coach-metric-ev">
          <InfoTip label="Call EV · check-down" explanation="Call EV is the estimated average chip gain versus folding if there are no further bets. Rake and future betting are excluded; raise EV is not calculated." />
          <strong>{t(analysis?.call_ev_available === false ? 'Not calculated' : analysis?.ev_call ?? '—')}</strong>
        </div>
        <div className="coach-metric">
          <span>{t("Hand")}</span>
          <strong>{t(label(analysis?.hand_strength.category))}</strong>
        </div>
        <div className="coach-metric">
          <span>{t("Preflop")}</span>
          <strong>{t(analysis?.preflop_profile.notation ?? '-')}</strong>
        </div>
      </div>

      {analysis ? (
        <div className="coach-summary">
          {analysis.rule_advice ? <div className="rule-advice"><strong>{t(analysis.rule_advice.hand_label)}</strong>{analysis.rule_advice.scenario ? <div><p>{t(analysis.rule_advice.scenario)}</p><p>{t('Your position')}: {t(hand?.players.find(p => p.id === analysis.player_id)?.position ?? '')}{analysis.rule_advice.opener_position ? ` · ${t('Opening position')}: ${t(analysis.rule_advice.opener_position)}` : ''}</p><p>{t('Effective stack')}: {analysis.rule_advice.effective_stack_bb} BB · {t(analysis.rule_advice.stack_band ?? '')}</p><p>{t(analysis.rule_advice.range_status ?? '')}</p>{analysis.rule_advice.range_hands?.length ? <details><summary>{t('Situation range')}</summary><p>{analysis.rule_advice.range_hands.join(', ')}</p></details> : null}</div> : null}<p>{analysis.rule_advice.board_texture.map(v => t(v)).join(' · ')}</p><p>{t('Action purpose')}: {t(analysis.rule_advice.purpose)}</p>{analysis.rule_advice.close_price ? <p>{t('Close to the call threshold; the range estimate can change this decision.')}</p> : null}</div> : null}
          <p>{t(analysis.coach_summary)}</p>
          {analysis.rule_advice ? <p className="room-note">{t(analysis.rule_advice.limitations)}</p> : null}
          {analysis.recommended_amount != null ? <p>{t('Suggested size uses a simple betting heuristic, not a solved optimal size. Raises show the total bet on this street.')}</p> : null}
          <div className="summary-meta">
            {analysis.rule_advice?.version === 'preflop_rules_v1' ? <span>{t('Educational preset')}</span> : <><span>{t("Heuristic score ")}{t(percent(analysis.confidence))}</span><span>{t("Risk ")}{t(label(analysis.risk_level))}</span></>}
            <span>{t(label(analysis.preflop_profile.category))}</span>
          </div>
          {analysis.preflop_profile.tags.length ? (
            <div className="tag-row">
              {analysis.preflop_profile.tags.map((tag) => (
                <span key={tag}>{t(label(tag))}</span>
              ))}
            </div>
          ) : null}
          {analysis.draw_profile.draws.length ? (
            <div className="draw-box">
              <strong>{t(analysis.draw_profile.outs)}{t(" estimated outs")}</strong>
              <span>{t(analysis.draw_profile.draws.map(label).join(', '))}</span>
            </div>
          ) : null}
          <ul>
            {analysis.key_factors.map((factor) => (
              <li key={factor}>{t(factor)}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {(analysis?.opponent_ranges?.length ? analysis.opponent_ranges : analysis?.opponent_range ? [analysis.opponent_range] : []).map((opponentRange) => (
        <details className="range-panel" key={opponentRange.player_id} open={analysis?.opponent_ranges?.length === 1}>
          <summary className="review-heading">
            <span>{displayPlayer(hand?.players.find((p) => p.id === opponentRange.player_id), t, t('Opponent'))}{t(" range")}</span>
            <strong>{t(label(opponentRange.position))}</strong>
          </summary>
          <p>{t(opponentRange.description)}</p>
          <div className="summary-meta">
            <span>{t(opponentRange.legal_combos)}{t(" legal combos")}</span>
            <span>{t(opponentRange.effective_combos)}{t(" effective combos")}</span>
          </div>
          <p className="range-detail">{t("Effective combos measure how concentrated the weights are; they are not a hard cutoff.")}</p>
          {opponentRange.top_hands.length ? (
            <div className="tag-row" aria-label={t("Hand classes with the most range weight")}>
              {opponentRange.top_hands.map((handClass) => <span key={handClass}>{t(handClass)}</span>)}
            </div>
          ) : null}
          {opponentRange.top_hands.length ? <p className="range-detail">{t("Largest total weights by hand class, including available suit combinations.")}</p> : null}
          {opponentRange.evidence.length ? (
            <p>{t("Observed: ")}{t(opponentRange.evidence.join(' → '))}</p>
          ) : null}
          <p className="range-detail">
            {t(analysis?.equity_method === 'exact_river'
              ? `Exact river enumeration · ${analysis?.equity_samples} combinations`
              : `${analysis?.equity_samples} simulations · 95% sampling bound ±${percent(analysis?.equity_sampling_error)}`)}{t(". Range-model uncertainty is additional.")}</p>
        </details>
      ))}

      {actionReview ? (
        <div className={`action-review review-${actionReview.verdict}`}>
          <div className="review-heading">
            <span>{t("Last decision")}</span>
            <strong>{t(label(actionReview.verdict))}</strong>
          </div>
          <p>{t(actionReview.summary)}</p>
          <div className="summary-meta">
            <span>{t("Chosen ")}{t(label(actionReview.chosen_action))}</span>
            <span>{t("Recommended ")}{t(label(actionReview.recommended_action))}</span>
          </div>
        </div>
      ) : null}

      {decisionLog.length ? (
        <div className="decision-log-panel">
          <div className="review-heading">
            <span>{t("Session decisions")}</span>
            <strong>{decisionStats.total}</strong>
          </div>
          <div className="decision-stats">
            <span>{t("Matches coach ")}{decisionStats.optimal}</span>
            <span>{t("Acceptable ")}{decisionStats.acceptable}</span>
            <span>{t("Review ")}{decisionStats.reconsider}</span>
          </div>
          <ol>
            {decisionLog.slice(0, 5).map((review, index) => (
              <li key={`${review.hand_id}-${review.street}-${index}`}>
                <span>{t(label(review.street))}</span>
                <strong>{t(label(review.verdict))}</strong>
                <em>
                  {t(label(review.chosen_action))}{t(" vs ")}{t(label(review.recommended_action))}
                </em>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {result ? (
        <div className="result-panel">
          <div>
            <span>{t("Result")}</span>
            <strong>{t(label(result.reason))}</strong>
          </div>
          <div>
            <span>{t("Winner")}</span>
            <strong>{result.winners.map((id) => displayPlayer(hand?.players.find((p) => p.id === id), t, id)).join(', ')}</strong>
          </div>
          <div>
            <span>{t("Pot awarded")}</span>
            <strong>{result.pot_awarded}</strong>
          </div>
          {result.pots?.map((pot, index) => (
            <div key={index} className="pot-result">
              <span>{t(index === 0 ? 'Main pot' : `Side pot ${index}`)} · {t(pot.amount)}</span>
              <strong>{Object.entries(pot.awards).map(([id, amount]) => `${displayPlayer(hand?.players.find((p) => p.id === id), t, id)} +${amount}`).join(', ')}</strong>
            </div>
          ))}
          <div className="result-list">
            {result.player_results.map((player) => (
              <p key={player.player_id}>
                <strong>{displayPlayer(hand?.players.find((p) => p.id === player.player_id), t, player.player_id)}</strong>
                <span>
                  {t(label(player.outcome))}
                  {t(player.hand_strength ? ` · ${label(player.hand_strength.category)}` : '')}
                  {t(player.amount_won ? ` · +${player.amount_won}` : '')}
                </span>
              </p>
            ))}
          </div>
        </div>
      ) : null}

      <div className="coach-notes">
        {(analysis?.notes.length ? analysis.notes : [result ? 'Hand complete. Choose the next hand to continue.' : 'Your decision analysis appears when it is your turn.']).map((note) => (
          <p key={note}>{t(note)}</p>
        ))}
      </div>
    </section>
  );
}
