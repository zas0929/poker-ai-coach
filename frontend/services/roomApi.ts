import type { HandState } from '@/types/poker';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
export interface RoomSettings { starting_stack: number; small_blind: number; big_blind: number; turn_seconds: number }
export interface RoomCredentials { code: string; token: string; player_id: string }
export interface RoomMember { player_id: string; name: string; ready: boolean; connected: boolean; sitting_out: boolean; seat: number; stack: number }
export interface RoomState {
  type: 'state'; code: string; revision: number; viewer_id: string; host_id: string;
  members: RoomMember[]; hand: HandState | null; viewer_left: boolean;
  settings: RoomSettings; saved: boolean;
  deadline_at: number | null; server_now: number; turn_seconds: number;
}
export function roomSocketUrl(code: string) {
  const url = new URL(`${API_BASE}/api/rooms/${encodeURIComponent(code)}/ws`);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}
export async function enterRoom(name: string, code?: string): Promise<RoomCredentials> {
  const response = await fetch(`${API_BASE}/api/rooms${code ? `/${encodeURIComponent(code)}/join` : ''}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not join the room. Check your name and room code.');
  }
  return response.json();
}
