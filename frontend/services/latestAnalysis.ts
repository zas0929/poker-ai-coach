import type { HandAnalysis, HandState } from '@/types/poker';

/** Keep only the hint for the latest table state, even if abort arrives too late. */
export class LatestAnalysis {
  private sequence = 0;
  private controller: AbortController | null = null;

  constructor(
    private load: (hand: HandState, signal: AbortSignal) => Promise<HandAnalysis>,
    private result: (analysis: HandAnalysis | null) => void,
    private loading: (value: boolean) => void,
    private error: (message: string) => void,
  ) {}

  cancel() {
    this.sequence += 1;
    this.controller?.abort();
    this.controller = null;
    this.result(null);
    this.loading(false);
  }

  async request(hand: HandState) {
    this.cancel();
    const sequence = this.sequence;
    const controller = new AbortController();
    this.controller = controller;
    this.loading(true);
    try {
      const analysis = await this.load(hand, controller.signal);
      if (sequence === this.sequence && !controller.signal.aborted) this.result(analysis);
    } catch (cause) {
      if (sequence === this.sequence && !controller.signal.aborted) {
        this.error(cause instanceof Error ? cause.message : 'Unknown error');
      }
    } finally {
      if (sequence === this.sequence) {
        this.controller = null;
        this.loading(false);
      }
    }
  }
}
