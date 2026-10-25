import { ensureProfile } from './trainingApi';
import type { ActionType, HandState } from '@/types/poker';

export interface TrainerModel {
  contract_version?: string; position_key?: string; hand_id?: string; client_position?: string;
  ticket_id: string | null; state: string; reason?: string | null;
  replaces_heuristic?: false;
  model?: {
    own_hand: string; actor_id: string; board: string[]; actions: string[];
    players: { id: string; total_committed: number; range?: { cards: string; weight: number }[] }[];
    tree: { bet_sizes: number[]; raise_sizes: number[]; max_raises: number };
    coverage: { player_id: string; selected_combos: number; public_combos: number; weight_share: number }[];
  } | null;
  quality?: { passed: boolean; value: number; gate: number } | null;
  actions?: { action: string; probability: number; ev_chips: number; gap_chips: number }[] | null;
}

/** Same explicit array as backend position_text. Never serialize other holdings. */
export function trainerPosition(hand: HandState): string {
  const entries = (value?: Record<string, number>) => Object.entries(value ?? {}).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  return JSON.stringify([
    hand.hand_id, hand.street, hand.current_player_id ?? null, hand.dealer_player_id,
    hand.small_blind, hand.big_blind, hand.last_full_raise ?? 0, hand.pot,
    hand.board.map(c => [c.rank, c.suit]),
    hand.players.map(p => [p.id, p.stack, p.current_bet, p.status, p.position]),
    hand.history.map(a => [a.player_id, a.action, a.amount ?? null, a.street]),
    entries(hand.contributions), entries(hand.acted_at_bet),
    hand.players.filter(p => p.id === 'hero').map(p => p.cards.map(c => [c.rank, c.suit])),
    Boolean(hand.result),
  ]);
}

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
async function request(path: string, signal?: AbortSignal, method = 'GET', body?: object): Promise<TrainerModel> {
  const profile = await ensureProfile();
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const response = await fetch(`${BASE}/api/hand/solver${path}`, {
    method, signal, cache: 'no-store', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${profile.token}` },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) throw new Error('Current calculation is unavailable. The usual coach remains available.');
  return response.json();
}
export const TrainerSolverApi = {
  submit: (position: string, nonce: string, signal: AbortSignal) => request('', signal, 'POST', { position, nonce }),
  poll: (ticket: string, signal: AbortSignal) => request(`/${encodeURIComponent(ticket)}`, signal),
  cancel: (ticket: string) => request(`/${encodeURIComponent(ticket)}`, undefined, 'DELETE'),
};

export function currentModelActions(result: TrainerModel | null, hand: HandState | null) {
  const model = result?.model, rows = result?.actions, quality = result?.quality;
  if (!hand || hand.result || hand.street !== 'river' || hand.current_player_id !== 'hero' ||
      result?.contract_version !== 'trainer_current_river_v1' || result.hand_id !== hand.hand_id ||
      result.state !== 'ready' || result.client_position !== trainerPosition(hand) || result.replaces_heuristic !== false || !model || model.actor_id !== 'hero' ||
      !rows?.length || !quality?.passed || !Number.isFinite(quality.value) || !Number.isFinite(quality.gate) ||
      quality.value < 0 || quality.gate <= 0 || quality.gate > .5 || quality.value > quality.gate ||
      rows.length !== model.actions.length || rows.some((r, i) => r.action !== model.actions[i]) ||
      model.own_hand.match(/../g)?.sort().join('') !== hand.players.find(p => p.id === 'hero')?.cards.map(c => c.rank + ({clubs:'c',diamonds:'d',hearts:'h',spades:'s'}[c.suit])).sort().join('') ||
      !rows.every(r => Number.isFinite(r.ev_chips) && Number.isFinite(r.gap_chips) && r.gap_chips >= 0 && Number.isFinite(r.probability) && r.probability >= 0 && r.probability <= 1) ||
      Math.abs(rows.reduce((sum, r) => sum + r.probability, 0) - 1) > 1e-8) return null;
  const hero = hand.players.find(p => p.id === 'hero');
  if (!hero || !hand.betting) return null;
  const maximum = hand.pot + hand.players.filter(p => p.id !== 'hero').reduce((sum, p) => sum + p.stack, 0);
  for (const row of rows) {
    const [label, text] = row.action.split(' '), action = label.toLowerCase();
    if (!hand.betting.legal_actions.includes(action as ActionType) || row.ev_chips < -hero.stack - 1e-7 || row.ev_chips > maximum + 1e-7 ||
        Math.abs(Math.max(...rows.map(r => r.ev_chips)) - row.ev_chips - row.gap_chips) > 1e-7) return null;
    if (action === 'bet' || action === 'raise') {
      const amount = Number(text), min = action === 'bet' ? hand.betting.min_bet : hand.betting.min_raise_to;
      if (!Number.isInteger(amount) || min == null || amount < min || amount > (hand.betting.max_raise_to ?? 0)) return null;
    } else if (text !== undefined) return null;
  }
  return rows;
}

function pause(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const stop = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', stop); resolve(); }, 600);
    signal.addEventListener('abort', stop, { once: true });
    if (signal.aborted) stop();
  });
}

/** Separate from quick hints: this controller never changes gameplay/loading. */
export class CurrentTrainerSolver {
  private sequence = 0;
  private controller: AbortController | null = null;
  private ticket: string | null = null;
  constructor(private update: (value: TrainerModel | null) => void, private api = TrainerSolverApi,
    private wait = pause, private nonce = () => crypto.randomUUID()) {}

  cancel() {
    this.sequence += 1;
    this.controller?.abort(); this.controller = null;
    if (this.ticket) void this.api.cancel(this.ticket).catch(() => {});
    this.ticket = null; this.update(null);
  }

  async request(hand: HandState) {
    this.cancel();
    if (hand.result || hand.street !== 'river' || hand.current_player_id !== 'hero') return;
    const sequence = this.sequence, controller = new AbortController(); this.controller = controller;
    let ticket: string | null = null;
    const current = () => sequence === this.sequence && !controller.signal.aborted;
    const timeout = setTimeout(() => controller.abort(), 30000);
    this.update({ state: 'preparing', ticket_id: null });
    try {
      let job = await this.api.submit(trainerPosition(hand), this.nonce(), controller.signal);
      ticket = job.ticket_id;
      if (!current()) { if (ticket) void this.api.cancel(ticket).catch(() => {}); return; }
      this.ticket = ticket;
      const key = job.position_key;
      if (job.state !== 'disabled' && (job.contract_version !== 'trainer_current_river_v1' || job.hand_id !== hand.hand_id || !key?.match(/^[a-f0-9]{64}$/))) throw new Error('identity');
      while (current()) {
        job = { ...job, client_position: trainerPosition(hand) };
        if (job.state === 'ready' && !currentModelActions(job, hand)) throw new Error('invalid');
        this.update(job);
        if (!['queued', 'running'].includes(job.state) || !ticket) break;
        await this.wait(controller.signal);
        if (!current()) return;
        job = await this.api.poll(ticket, controller.signal);
        if (!current()) return;
        if (job.position_key !== key || job.hand_id !== hand.hand_id || job.ticket_id !== ticket || job.contract_version !== 'trainer_current_river_v1') throw new Error('identity');
      }
    } catch {
      if (sequence === this.sequence) this.update({ state: 'unavailable', reason: 'CURRENT_RIVER_UNAVAILABLE', ticket_id: null });
      if (ticket) void this.api.cancel(ticket).catch(() => {});
    } finally {
      clearTimeout(timeout);
      if (sequence === this.sequence) this.controller = null;
    }
  }
}
