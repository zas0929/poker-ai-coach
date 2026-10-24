import type { HandState } from '@/types/poker';

function pause(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(signal.reason ?? new Error('Playback cancelled')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, milliseconds);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) { signal.removeEventListener('abort', abort); abort(); }
  });
}

/** Reveal one bot action at a time while its calculation runs during the thinking pause. */
export async function playTrainerTurns(initial: HandState, options: {
  aiAction: (playerId: string, signal: AbortSignal) => Promise<HandState>;
  advance: (signal: AbortSignal) => Promise<HandState>;
  onState: (state: HandState) => void;
  signal: AbortSignal;
  wait?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  random?: () => number;
}): Promise<HandState> {
  let state = initial;
  const { signal, onState, wait = pause, random = Math.random } = options;
  for (let step = 0; step < 512; step++) {
    signal.throwIfAborted();
    if (state.result || state.street === 'showdown' || state.current_player_id === 'hero') return state;
    if (state.current_player_id) {
      const [next] = await Promise.all([
        options.aiAction(state.current_player_id, signal),
        wait(1000 + Math.floor(random() * 1001), signal),
      ]);
      state = next;
    } else {
      state = await options.advance(signal);
    }
    signal.throwIfAborted();
    onState(state);
  }
  throw new Error('Too many trainer actions. Reload the table to continue.');
}
