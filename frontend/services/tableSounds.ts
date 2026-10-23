import type { HandState } from '@/types/poker';

// Only new public actions make sounds; snapshots and reconnects must not replay a hand.
export function newActionSounds(previous: HandState | null, hand: HandState) {
  if (!previous || previous.hand_id !== hand.hand_id || previous.history.length > hand.history.length) return [];
  return hand.history.slice(previous.history.length).flatMap(action =>
    action.action === 'check' ? ['check' as const] : ['bet', 'raise', 'call', 'small_blind', 'big_blind'].includes(action.action) ? ['chips' as const] : []);
}
