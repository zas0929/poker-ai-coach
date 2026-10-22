import { ensureProfile } from './trainingApi';

import type { HandAnalysis, HandState, PlayerActionRequest } from '@/types/poker';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const profile = await ensureProfile();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${profile.token}`,
      ...(options?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;

    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      // Keep the status-based fallback message.
    }

    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export const PokerApi = {
  startHand(playerCount?: number) {
    const query = playerCount === undefined ? '' : `?player_count=${playerCount}`;
    return request<HandState>(`/api/hand/start${query}`, { method: 'POST' });
  },

  getState() {
    return request<HandState>('/api/hand/state');
  },

  analyze(playerId = 'hero', hand?: HandState, signal?: AbortSignal) {
    const query = new URLSearchParams({ player_id: playerId });
    if (hand) {
      query.set('hand_id', hand.hand_id);
      query.set('history_length', String(hand.history.length));
      query.set('street', hand.street);
    }
    return request<HandAnalysis>(`/api/hand/analyze?${query}`, { signal });
  },

  action(payload: PlayerActionRequest) {
    return request<HandState>('/api/hand/action', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  aiAction(playerId = 'villain') {
    return request<HandState>(`/api/hand/ai-action?player_id=${playerId}`, {
      method: 'POST',
    });
  },

  autoPlay() {
    return request<HandState>('/api/hand/auto-play', { method: 'POST' });
  },

  advance() {
    return request<HandState>('/api/hand/advance', { method: 'POST' });
  },
};
