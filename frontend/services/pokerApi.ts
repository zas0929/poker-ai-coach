import type { HandAnalysis, HandState, PlayerActionRequest } from '@/types/poker';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
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
  startHand() {
    return request<HandState>('/api/hand/start', { method: 'POST' });
  },

  getState() {
    return request<HandState>('/api/hand/state');
  },

  analyze(playerId = 'hero') {
    return request<HandAnalysis>(`/api/hand/analyze?player_id=${playerId}`);
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

  advance() {
    return request<HandState>('/api/hand/advance', { method: 'POST' });
  },
};
