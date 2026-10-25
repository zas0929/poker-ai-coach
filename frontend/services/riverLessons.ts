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
export interface LessonAnalysis {
  status: string; reasons: { code: string }[];
  quality: null | { value: number; gate: number; passed: boolean };
  candidate: null | { actions: string[]; probabilities: number[]; own_hand: string };
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
};
export function lessonError(code: string) { return ERRORS[code] ?? 'Could not complete the river calculation. Please retry.'; }
async function request<T>(path: string, signal?: AbortSignal, method = 'GET', body?: object): Promise<T> {
  const profile = path.startsWith('/jobs') ? await ensureProfile() : null;
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
