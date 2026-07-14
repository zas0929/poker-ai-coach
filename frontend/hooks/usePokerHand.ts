import { useCallback, useEffect, useState } from 'react';

import { PokerApi } from '@/services/pokerApi';
import type { ActionReview, ActionType, HandAnalysis, HandState } from '@/types/poker';

export function usePokerHand() {
  const [hand, setHand] = useState<HandState | null>(null);
  const [analysis, setAnalysis] = useState<HandAnalysis | null>(null);
  const [actionReview, setActionReview] = useState<ActionReview | null>(null);
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

      const shouldAutoPlay =
        !settledHand.result &&
        settledHand.street !== 'showdown' &&
        (settledHand.current_player_id === 'villain' || settledHand.current_player_id === null);

      if (shouldAutoPlay) {
        const autoResult = await run(() => PokerApi.autoPlay());
        if (autoResult) {
          settledHand = autoResult;
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
      setActionReview(null);
      await applyState(result);
    }
  }, [applyState, run]);

  const action = useCallback(
    async (actionType: ActionType, amount?: number) => {
      const preActionAnalysis =
        hand?.current_player_id === 'hero'
          ? await run(() => PokerApi.analyze('hero'))
          : null;

      const result = await run(() =>
        PokerApi.action({
          player_id: hand?.current_player_id ?? 'hero',
          action: actionType,
          amount,
        }),
      );

      if (result) {
        if (preActionAnalysis) {
          setActionReview(reviewAction(actionType, preActionAnalysis));
        }
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
    actionReview,
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

function reviewAction(actionType: ActionType, analysis: HandAnalysis): ActionReview {
  const recommended = analysis.recommended_action;

  if (actionType === recommended) {
    return {
      chosen_action: actionType,
      recommended_action: recommended,
      verdict: 'optimal',
      summary: `Good decision. ${analysis.coach_summary}`,
    };
  }

  const acceptablePairs = new Set([
    'call:raise',
    'raise:call',
    'check:bet',
    'bet:check',
  ]);
  const isAcceptable = acceptablePairs.has(`${actionType}:${recommended}`);

  if (isAcceptable && analysis.confidence < 0.7) {
    return {
      chosen_action: actionType,
      recommended_action: recommended,
      verdict: 'acceptable',
      summary: `Reasonable alternative. The engine preferred ${recommended}, but confidence was not high enough to call your ${actionType} a clear mistake.`,
    };
  }

  return {
    chosen_action: actionType,
    recommended_action: recommended,
    verdict: 'reconsider',
    summary: `Review this spot. The engine preferred ${recommended}, while you chose ${actionType}. ${analysis.coach_summary}`,
  };
}
