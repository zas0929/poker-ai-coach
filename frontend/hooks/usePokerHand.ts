import { useCallback, useEffect, useRef, useState } from 'react';

import { PokerApi } from '@/services/pokerApi';
import type { ActionReview, ActionType, HandAnalysis, HandState } from '@/types/poker';

export function usePokerHand() {
  const [hand, setHand] = useState<HandState | null>(null);
  const [analysis, setAnalysis] = useState<HandAnalysis | null>(null);
  const [actionReview, setActionReview] = useState<ActionReview | null>(null);
  const [decisionLog, setDecisionLog] = useState<ActionReview[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const busy = useRef(false);
  const tableSize = useRef<number | null>(null);

  const run = useCallback(async <T,>(task: () => Promise<T>) => {
    if (busy.current) return null;
    busy.current = true;
    setIsLoading(true);
    setError(null);

    try {
      return await task();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      return null;
    } finally {
      busy.current = false;
      setIsLoading(false);
    }
  }, []);

  const analyze = useCallback(async () => {
    const result = await run(() => PokerApi.analyze('hero'));
    if (result) {
      setAnalysis(result);
    }
  }, [run]);

  const applyState = useCallback(async (nextHand: HandState) => {
    let settledHand = nextHand;
    setAnalysis(null);
    setHand(settledHand);
    if (!settledHand.result && settledHand.current_player_id !== 'hero') {
      settledHand = await PokerApi.autoPlay();
      setHand(settledHand);
    }
    const hero = settledHand.players.find((p) => p.id === 'hero');
    if (!settledHand.result && hero?.status !== 'folded') {
      setAnalysis(await PokerApi.analyze('hero'));
    }
  }, []);

  const startHand = useCallback(async (playerCount?: number) => run(async () => {
    setAnalysis(null);
    setActionReview(null);
    const next = await PokerApi.startHand(playerCount);
    if (tableSize.current !== null && tableSize.current !== next.players.length) setDecisionLog([]);
    tableSize.current = next.players.length;
    await applyState(next);
  }), [applyState, run]);

  const action = useCallback(async (actionType: ActionType, amount?: number) => run(async () => {
    const before = hand?.current_player_id === 'hero' ? await PokerApi.analyze('hero') : null;
    const result = await PokerApi.action({player_id: 'hero', action: actionType, amount});
    if (before) {
      const review = reviewAction(actionType, before);
      setActionReview(review);
      setDecisionLog((current) => [review, ...current].slice(0, 25));
    }
    await applyState(result);
  }), [applyState, hand, run]);

  const advance = useCallback(async () => run(async () => {
    await applyState(await PokerApi.advance());
  }), [applyState, run]);

  useEffect(() => {
    void startHand();
  }, [startHand]);

  return {
    analysis,
    actionReview,
    decisionLog,
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
      hand_id: analysis.hand_id,
      street: analysis.street,
      chosen_action: actionType,
      recommended_action: recommended,
      verdict: 'optimal',
      summary: `Matches the coach heuristic. ${analysis.coach_summary}`,
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
      hand_id: analysis.hand_id,
      street: analysis.street,
      chosen_action: actionType,
      recommended_action: recommended,
      verdict: 'acceptable',
      summary: `Reasonable alternative. The engine preferred ${recommended}, but confidence was not high enough to call your ${actionType} a clear mistake.`,
    };
  }

  return {
    hand_id: analysis.hand_id,
    street: analysis.street,
    chosen_action: actionType,
    recommended_action: recommended,
    verdict: 'reconsider',
    summary: `Review this spot. The engine preferred ${recommended}, while you chose ${actionType}. ${analysis.coach_summary}`,
  };
}
