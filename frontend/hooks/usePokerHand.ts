import { useCallback, useEffect, useState } from 'react';

import { PokerApi } from '@/services/pokerApi';
import type { ActionType, HandAnalysis, HandState } from '@/types/poker';

export function usePokerHand() {
  const [hand, setHand] = useState<HandState | null>(null);
  const [analysis, setAnalysis] = useState<HandAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const run = useCallback(async <T,>(task: () => Promise<T>) => {
    setIsLoading(true);
    setError(null);

    try {
      return await task();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const analyze = useCallback(async () => {
    const result = await run(() => PokerApi.analyze('hero'));
    if (result) {
      setAnalysis(result);
    }
  }, [run]);

  const applyState = useCallback(
    async (nextHand: HandState) => {
      let settledHand = nextHand;
      setHand(settledHand);

      if (settledHand.current_player_id === 'villain' && !settledHand.result) {
        const aiResult = await run(() => PokerApi.aiAction('villain'));
        if (aiResult) {
          settledHand = aiResult;
          setHand(settledHand);
        }
      }

      const nextAnalysis = await run(() => PokerApi.analyze('hero'));
      if (nextAnalysis) {
        setAnalysis(nextAnalysis);
      }
    },
    [run],
  );

  const startHand = useCallback(async () => {
    const result = await run(() => PokerApi.startHand());
    if (result) {
      setAnalysis(null);
      await applyState(result);
    }
  }, [applyState, run]);

  const action = useCallback(
    async (actionType: ActionType, amount?: number) => {
      const result = await run(() =>
        PokerApi.action({
          player_id: hand?.current_player_id ?? 'hero',
          action: actionType,
          amount,
        }),
      );

      if (result) {
        await applyState(result);
      }
    },
    [applyState, hand?.current_player_id, run],
  );

  const advance = useCallback(async () => {
    const result = await run(() => PokerApi.advance());
    if (result) {
      await applyState(result);
    }
  }, [applyState, run]);

  useEffect(() => {
    void startHand();
  }, [startHand]);

  return {
    analysis,
    error,
    hand,
    isLoading,
    action,
    advance,
    analyze,
    clearError: () => setError(null),
    startHand,
  };
}
