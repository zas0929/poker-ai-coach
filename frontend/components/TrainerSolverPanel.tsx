'use client';
import { useI18n } from '@/i18n/LanguageProvider';
import { currentModelActions, type TrainerModel } from '@/services/trainerSolver';
import type { HandAnalysis, HandState } from '@/types/poker';
const reasons: Record<string, string> = {
  TRAINER_SOLVER_DISABLED: 'Current calculation is not connected on this server.',
  TRAINER_SOLVER_BUSY: 'The calculation queue is busy. The usual coach remains available.',
  TIME_BUDGET_EXCEEDED: 'The calculation reached its time limit. The usual coach remains available.',
  MODEL_BUDGET_EXCEEDED: 'This position exceeds the small model tree budget. The usual coach remains available.',
  MEMORY_BUDGET_EXCEEDED: 'This model exceeds the calculation budget.',
  QUALITY_GATE_FAILED: 'This strategy did not pass the model quality check.',
  STALE_DECISION: 'The position changed. The old calculation was discarded.',
  UNSUPPORTED_STATE_OR_TREE: 'This position does not fit the small model.',
  UNSUPPORTED_OWN_HAND: 'These assumed hands have no compatible deal with your cards.',
  CURRENT_TURN_UNSUPPORTED: 'This position does not fit the small model.',
  CURRENT_RIVER_UNSUPPORTED: 'This position does not fit the small model.',
};
export default function TrainerSolverPanel({ result, hand, analysis, onRetry }: {
  result: TrainerModel | null; hand: HandState | null; analysis?: HandAnalysis | null; onRetry?: () => void;
}) {
  const { t } = useI18n();
  if (!result || !hand || hand.result || !['turn', 'river'].includes(hand.street) || hand.current_player_id !== 'hero') return null;
  const title = hand.street === 'turn' ? 'Current turn model' : 'Current river model';
  const busy = ['preparing', 'queued', 'running'].includes(result.state);
  const rows = currentModelActions(result, hand);
  const coverage = result.model?.coverage ?? [];
  const minimum = coverage.length ? Math.min(...coverage.map(p => p.weight_share)) : null;
  const best = rows ? Math.max(...rows.map(row => row.ev_chips)) : null;
  const preferred = rows?.filter(row => Math.abs(row.ev_chips - (best ?? 0)) < 1e-7) ?? [];
  const advice = analysis?.hand_id === hand.hand_id && analysis.street === hand.street && analysis.pot === hand.pot ? analysis.recommended_action : null;
  const disagreement = advice && preferred.length && preferred.every(row => row.action.split(' ')[0].toLowerCase() !== advice);
  const counts = [...new Set(coverage.map(p => p.selected_combos))].sort((a, b) => a - b).join(' / ');
  return <section className="trainer-solver" aria-label={t(title)}>
    <div className="trainer-solver-heading"><strong>{t(title)}</strong><span role="status">{t(busy ? 'Calculating in background' : rows ? 'Experimental model calculated' : 'Calculation unavailable')}</span></div>
    <p className="trainer-solver-warning">{t('Limited range model. Advice reliability has not been established.')}</p>
    {disagreement ? <p className="trainer-solver-warning">{t('The model and heuristic coach disagree. Range sensitivity has not been checked for this decision.')}</p> : null}
    {busy ? <p className="trainer-solver-progress">{t('You can act while the calculation runs.')}</p> : null}
    {rows ? <>
      <div className="trainer-solver-actions">{rows.map(row => <div className={`trainer-solver-action${row.ev_chips === best ? ' trainer-solver-best' : ''}`} key={row.action}>
        <strong>{row.action.startsWith('RAISE ') ? `${t('Raise to')} ${row.action.split(' ')[1]}` : row.action.startsWith('BET ') ? `${t('bet')} ${row.action.split(' ')[1]}` : t(row.action.toLowerCase())}</strong><span>{t('Frequency')} <b>{(row.probability * 100).toFixed(1)}%</b></span><span>EV <b>{row.ev_chips.toFixed(2)}</b></span><span>{t('Difference')} <b>{row.gap_chips.toFixed(2)}</b></span>
      </div>)}</div>
      <p>{t('EV starts at this decision and uses the same learned continuation after each first action.')}</p>
      <p>{t('Selected combos per player: {0}; minimum range coverage {1}%.').replace('{0}', counts || '—').replace('{1}', ((minimum ?? 0) * 100).toFixed(2))}</p>
      <p>{t('Frequencies and EV apply only to selected hands. A frequency of 100% is not a win probability.')}</p>
      {hand.street === 'turn' ? <>
        <p>{t('All compatible river cards; future raises: turn {0}, river {1}.').replace('{0}', String(result.model?.tree.turn_max_raises ?? 0)).replace('{1}', String(result.model?.tree.river_max_raises ?? 0))}</p>
        <p>{t('Model sizes: turn bet {0}, raise to {1}; river bet {2}.').replace('{0}', result.model?.tree.turn_bet_sizes?.join(', ') || '—').replace('{1}', result.model?.tree.turn_raise_sizes?.join(', ') || '—').replace('{2}', result.model?.tree.river_bet_sizes?.join(', ') || '—')}</p>
      </> : <p>{t('Future raise limit: {0}.').replace('{0}', String(result.model?.tree.max_raises ?? 0))}</p>}
      <p>{t('Deviation within this model: {0}% of the pot. This does not measure full-range advice accuracy.').replace('{0}', (result.quality?.value ?? 0).toFixed(3))}</p>
      <details><summary>{t('Assumed hands')}</summary>{result.model?.players.filter(p => p.range).map(p => <p key={p.id}><strong>{p.id === 'hero' ? t('You') : hand.players.find(seat => seat.id === p.id)?.name ?? p.id}</strong>: {p.range?.map(r => r.cards).join(', ')}</p>)}</details>
    </> : !busy ? <p>{t(reasons[result.reason ?? ''] ?? 'Current calculation is unavailable. The usual coach remains available.')}</p> : null}
    {!busy && result.state !== 'disabled' && onRetry ? <button onClick={onRetry}>{t('Recalculate model')}</button> : null}
  </section>;
}
