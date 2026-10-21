import type { ActionReview, ActionType, HandAnalysis, HandState } from '@/types/poker';

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
export type ExerciseKind = 'call_price' | 'legal_actions';
export interface TrainingProgress { attempts: number; correct_attempts: number; questions: number; last_answer_correct: number; to_review: number }
export interface Exercise {
  question_id: string; kind: ExerciseKind; prompt: string; source: string; hand: HandState;
  context: { pot: number; call_amount: number; uncalled_return?: number; contestable_pot?: number; highest_bet: number; last_full_raise: number; hero_acted_at_bet: number | null };
}
export interface ExerciseResult { question_id: string; correct: boolean; expected: number | ActionType[]; explanation: string; tolerance_percentage_points: number | null }
export interface SavedDecision {
  decision_id: number; created_at: string; hand: HandState; analysis: HandAnalysis;
  chosen_action: ActionType; amount: number | null; review: ActionReview;
  exercises: Partial<Record<ExerciseKind, string>>;
}
interface TrainingProfile { profile_id: string; token: string }
let profilePromise: Promise<TrainingProfile> | null = null;

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}
export async function ensureProfile(): Promise<TrainingProfile> {
  if (!profilePromise) {
    profilePromise = (async () => {
      try {
        const saved = localStorage.getItem('poker-training-profile');
        if (saved) {
          const parsed = JSON.parse(saved);
          if (typeof parsed.profile_id === 'string' && typeof parsed.token === 'string') return parsed;
        }
      } catch { /* Browser storage may be unavailable. */ }
      const created = await parse<TrainingProfile>(await fetch(`${BASE}/api/training/profiles`, { method: 'POST' }));
      try { localStorage.setItem('poker-training-profile', JSON.stringify(created)); } catch { /* Keep the profile in memory. */ }
      return created;
    })().catch((error) => { profilePromise = null; throw error; });
  }
  return profilePromise;
}
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const profile = await ensureProfile();
  return parse<T>(await fetch(`${BASE}/api/training${path}`, {
    ...options, cache: 'no-store', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${profile.token}` },
  }));
}
export const TrainingApi = {
  action(hand: HandState, action: ActionType, amount?: number) {
    return request<{ state: HandState; review: ActionReview; decision_id: number }>('/decision', {
      method: 'POST', body: JSON.stringify({ command_id: crypto.randomUUID(), hand_id: hand.hand_id, history_length: hand.history.length, action, amount }),
    });
  },
  progress() { return request<TrainingProgress>('/progress'); },
  decisions(before?: number) { return request<{ items: SavedDecision[]; next_cursor: number | null }>(`/decisions${before ? `?before=${before}` : ''}`); },
  next(kind: ExerciseKind, exclude?: string) { return request<Exercise>(`/exercises/next?kind=${kind}${exclude ? `&exclude=${encodeURIComponent(exclude)}` : ''}`); },
  exercise(id: string) { return request<Exercise>(`/exercises/${encodeURIComponent(id)}`); },
  answer(payload: { question_id: string; attempt_id: string; percent?: number; actions?: ActionType[] }) {
    return request<ExerciseResult>('/answers', { method: 'POST', body: JSON.stringify(payload) });
  },
};
