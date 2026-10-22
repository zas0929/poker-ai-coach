import type { HandState } from '@/types/poker';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
export interface RoomSettings { starting_stack: number; small_blind: number; big_blind: number; turn_seconds: number; auto_deal: boolean }
export interface RoomCredentials { code: string; token: string; player_id: string }
export interface RoomMember { player_id: string; name: string; ready: boolean; connected: boolean; sitting_out: boolean; seat: number; stack: number }
export interface RoomState {
  type: 'state'; code: string; revision: number; viewer_id: string; host_id: string;
  members: RoomMember[]; hand: HandState | null; viewer_left: boolean;
  settings: RoomSettings; saved: boolean;
  next_hand_at?: number | null; deadline_at: number | null; server_now: number; turn_seconds: number; turn_grace_seconds?: number;
}
export function roomSocketUrl(code: string) {
  const url = new URL(`${API_BASE}/api/rooms/${encodeURIComponent(code)}/ws`);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}
export async function enterRoom(name: string, code?: string, buyIn?: number, settings?: RoomSettings): Promise<RoomCredentials> {
  const response = await fetch(`${API_BASE}/api/rooms${code ? `/${encodeURIComponent(code)}/join` : ''}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, buy_in: buyIn, ...(code ? {} : { settings }) }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not join the room. Check your name and room code.');
  }
  return response.json();
}

export interface ArchivedHandSummary {
  hand_id: string; cursor: number; completed_at: string; reason: string;
  pot_awarded: number; player_count: number; own_cards: import('@/types/poker').Card[];
  board: import('@/types/poker').Card[]; amount_won: number; committed: number; net: number; winners: string[];
}
export interface ArchivePage { items: ArchivedHandSummary[]; next_cursor: number | null }
export interface DecisionFacts {
  action: string; description: string; pot_before: number; stack_before: number;
  call_amount: number; committed_by_action: number; break_even_equity: number | null;
  made_hand: string; note: string;
}
export interface ArchivedHand {
  hand_id: string; viewer_id: string; hand: HandState;
  frames: { label: string; hand: HandState; decision: DecisionFacts | null }[];
  warning: string | null; review_note: string;
}
async function archiveRequest<T>(credentials: RoomCredentials, path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}/api/rooms/${encodeURIComponent(credentials.code)}/history${path}`, {
    headers: { Authorization: `Bearer ${credentials.token}` }, signal, cache: 'no-store',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not load hand history.');
  }
  return response.json();
}
export const HandArchiveApi = {
  list(credentials: RoomCredentials, signal: AbortSignal, before?: number) {
    return archiveRequest<ArchivePage>(credentials, before ? `?before=${before}` : '', signal);
  },
  hand(credentials: RoomCredentials, handId: string, signal: AbortSignal) {
    return archiveRequest<ArchivedHand>(credentials, `/${encodeURIComponent(handId)}`, signal);
  },
};
