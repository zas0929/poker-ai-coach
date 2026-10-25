const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
import { ensureProfile } from './trainingApi';

export interface RiverLesson {
  id: string; opponents: number; board: string[]; own_hand: string; actor_id: string; button_id: string;
  pot: number; small_blind: number; big_blind: number; actions: string[];
  players: { id: string; seat: number; stack: number; street_committed: number; total_committed: number;
    status: string; range?: { cards: string; weight: number }[] }[];
  tree: { bet_sizes: number[]; raise_sizes: number[]; max_raises: number };
}
export interface RiverCatalog {
  enabled: boolean; version: string | null; lessons: RiverLesson[]; reason?: string;
  limits?: { wall_seconds: number; iterations: number; quality_gate_pct_pot: number };
}
export interface LessonActionValues {
  version: string; actor_id: string; own_hand: string; actions: string[];
  ev_chips: number[]; gap_to_best_chips: number[]; policy_ev_chips: number;
  sunk_chips: number; baseline: string; continuation: string;
}
export interface LessonAnalysis {
  status: string; reasons: { code: string }[];
  quality: null | { value: number; gate: number; passed: boolean };
  candidate: null | { actions: string[]; probabilities: number[]; own_hand: string };
  action_values?: LessonActionValues;
  admission: { offline_analysis_allowed: boolean; live_advice_allowed: boolean };
}
export interface LessonJob {
  ticket_id: string; lesson_id: string; version: string; state?: string; status?: string;
  result?: LessonAnalysis | null;
}

const ERRORS: Record<string, string> = {
  LESSON_NOT_ENABLED: 'River calculation is not connected on this server.',
  LESSON_ENGINE_UNAVAILABLE: 'The river calculation engine is unavailable.',
  LESSON_VERSION_CHANGED: 'The examples have changed. Reload this page.',
  LESSON_NOT_FOUND: 'This example is unavailable.',
  LESSON_JOB_NOT_FOUND: 'This calculation has expired. Start it again.',
  LESSON_BUSY: 'The calculation queue is full. Try again shortly.',
  HISTORY_NOT_FOUND: 'This completed river decision is unavailable.',
  HISTORY_UNAVAILABLE: 'Saved river history is unavailable.',
  HISTORY_SNAPSHOT_UNAVAILABLE: 'This saved decision cannot be reconstructed safely.',
  HISTORY_INVALID_SIZES: 'Use one or two positive integer sizes, up to 10000.',
  HISTORY_SELECT_TWO_HANDS: 'Choose exactly two distinct hands for every live seat.',
};
export function lessonError(code: string) { return ERRORS[code] ?? 'Could not complete the river calculation. Please retry.'; }
async function request<T>(path: string, signal?: AbortSignal, method = 'GET', body?: object): Promise<T> {
  const profile = (path.startsWith('/jobs') || path.startsWith('/history')) ? await ensureProfile() : null;
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const response = await fetch(`${BASE}/api/river-lessons${path}`, {
    method, signal, cache: 'no-store', headers: { 'Content-Type': 'application/json',
      ...(profile ? { Authorization: `Bearer ${profile.token}` } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(lessonError(typeof data.detail === 'string' ? data.detail : ''));
  }
  return response.json();
}
export const RiverLessonsApi = {
  catalog: (signal?: AbortSignal) => request<RiverCatalog>('', signal),
  submit: (lesson_id: string, version: string, signal?: AbortSignal) => request<LessonJob>('/jobs', signal, 'POST', { lesson_id, version }),
  poll: (ticket: string, signal?: AbortSignal) => request<LessonJob>(`/jobs/${encodeURIComponent(ticket)}`, signal),
  cancel: (ticket: string) => request<LessonJob>(`/jobs/${encodeURIComponent(ticket)}`, undefined, 'DELETE'),
};
export function isLessonTerminal(job: LessonJob) {
  return ['completed', 'stale', 'cancelled', 'error', 'expired'].includes(job.state ?? '');
}
export function lessonResultMatches(job: LessonJob, id: string, version: string) {
  return job.lesson_id === id && job.version === version;
}

export async function followLessonJob(
  ticket: string, lesson: string, version: string, signal: AbortSignal,
  update: (job: LessonJob) => void, poll = RiverLessonsApi.poll,
): Promise<LessonJob> {
  const linked = new AbortController();
  const cancel = () => linked.abort();
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  signal.addEventListener('abort', cancel, { once: true });
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; linked.abort(); }, 45000);
  const pause = () => new Promise<void>((resolve, reject) => {
    const stop = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { linked.signal.removeEventListener('abort', stop); resolve(); }, 600);
    linked.signal.addEventListener('abort', stop, { once: true });
    if (linked.signal.aborted) stop();
  });
  try {
    while (!linked.signal.aborted) {
      const next = await poll(ticket, linked.signal);
      if (linked.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      if (!lessonResultMatches(next, lesson, version) || next.state === 'expired') throw new Error('This calculation has expired. Start it again.');
      update(next);
      if (isLessonTerminal(next)) return next;
      await pause();
    }
    throw new DOMException('Aborted', 'AbortError');
  } catch (cause) {
    if (timedOut) throw new Error('The calculation reached its time limit. You can try another example.');
    throw cause;
  } finally {
    clearTimeout(timeout); signal.removeEventListener('abort', cancel);
  }
}

// Older/partial results can still display frequencies, but never unverified EV.
export function lessonActionValues(result: LessonAnalysis | null | undefined, lesson: RiverLesson | undefined) {
  const values = result?.action_values, candidate = result?.candidate;
  if (!lesson || result?.status !== 'ready' || !result.quality?.passed ||
      !result.admission.offline_analysis_allowed || result.admission.live_advice_allowed !== false || !candidate || !values ||
      values.version !== 'fixed_policy_decision_ev_v1' || values.baseline !== 'current_decision' ||
      values.continuation !== 'fixed_learned_policy' || values.actor_id !== lesson.actor_id ||
      values.own_hand !== lesson.own_hand || candidate.own_hand !== lesson.own_hand ||
      JSON.stringify(values.actions) !== JSON.stringify(candidate.actions) ||
      JSON.stringify(values.actions) !== JSON.stringify(lesson.actions)) return null;
  if (!Array.isArray(candidate.probabilities) || candidate.probabilities.length !== values.actions.length ||
      !candidate.probabilities.every(p => Number.isFinite(p) && p >= 0 && p <= 1) ||
      Math.abs(candidate.probabilities.reduce((sum, p) => sum + p, 0) - 1) > 1e-8 ||
      values.sunk_chips !== lesson.players.find(p => p.id === lesson.actor_id)?.total_committed) return null;
  const chips = values.ev_chips, gaps = values.gap_to_best_chips;
  if (!Array.isArray(chips) || !Array.isArray(gaps) || chips.length !== values.actions.length || gaps.length !== chips.length ||
      chips.length === 0 || !chips.every(Number.isFinite) || !gaps.every(Number.isFinite) ||
      !Number.isFinite(values.policy_ev_chips) || !Number.isFinite(values.sunk_chips) ||
      gaps.some((gap, i) => gap < 0 || Math.abs(Math.max(...chips) - chips[i] - gap) > 1e-7) ||
      Math.abs(candidate.probabilities.reduce((sum, p, i) => sum + p * chips[i], 0) - values.policy_ev_chips) > 1e-7) return null;
  return values;
}

export interface HistoryRiverModel {
  selected_hands: Record<string, string[]>; bet_sizes: number[]; raise_sizes: number[]; max_raises: number;
}
export interface HistoryRiverDecision {
  decision_id: number; hand_id: string; created_at: string; completed_at: string;
  chosen_action: string; amount: number | null;
}
export interface HistoryRiverAssessment {
  decision_id: number; hand_id: string; completed_at: string; source_version: string; version: string | null;
  supported: boolean; reason: string | null; lesson: RiverLesson; model: HistoryRiverModel;
  chosen_action: string; chosen_amount: number | null; heuristic_action?: string | null; heuristic_amount?: number | null; joint_deals?: number; public_nodes?: number;
  coverage: { player_id: string; public_combos: number; selected_combos: number; weight_share: number }[];
}
export const RiverHistoryApi = {
  list: (before?: number, signal?: AbortSignal) => request<{items: HistoryRiverDecision[]; next_cursor: number | null}>(`/history${before ? `?before=${before}` : ''}`, signal),
  detail: (id: number, signal?: AbortSignal) => request<HistoryRiverAssessment>(`/history/${id}`, signal),
  submit: (id: number, version: string, model: HistoryRiverModel, signal?: AbortSignal) =>
    request<{ticket_id:string|null; lesson_id?:string; version?:string; assessment:HistoryRiverAssessment}>(`/history/${id}/jobs`, signal, 'POST', {version, ...model}),
};
export const HISTORY_REASONS: Record<string, string> = {
  HISTORY_SELECT_TWO_HANDS: 'Choose exactly two distinct hands for every live seat.',
  HISTORY_INVALID_HANDS: 'Use two distinct legal combinations per seat, such as AsKd 7h7d. Board cards cannot be used.',
  HISTORY_OWN_HAND_REQUIRED: 'Your range must include your saved hand and one alternative.',
  HISTORY_CARD_COLLISIONS: 'No compatible deal includes your hand. Change the assumed ranges.',
  HISTORY_TREE_TOO_LARGE: 'The tree exceeds the model budget. Use fewer sizes or disable future raises.',
  HISTORY_UNSUPPORTED_TREE: 'These ranges or bet sizes do not fit the bounded model. Try smaller sizes or disable future raises.',
};
