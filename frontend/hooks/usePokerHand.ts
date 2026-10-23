import { useCallback, useEffect, useRef, useState } from 'react';

import { LatestAnalysis } from '@/services/latestAnalysis';
import { PokerApi, type TrainingBlinds } from '@/services/pokerApi';
import { TrainingApi } from '@/services/trainingApi';
import type { ActionReview, ActionType, HandAnalysis, HandState } from '@/types/poker';

export function usePokerHand() {
  const [hand, setHand] = useState<HandState | null>(null);
  const [analysis, setAnalysis] = useState<HandAnalysis | null>(null);
  const [actionReview, setActionReview] = useState<ActionReview | null>(null);
  const [decisionLog, setDecisionLog] = useState<ActionReview[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const hints = useRef<LatestAnalysis | null>(null);
  if (hints.current === null) {
    hints.current = new LatestAnalysis(
      (state, signal) => PokerApi.analyze('hero', state, signal),
      setAnalysis, setIsAnalyzing, setError,
    );
  }
  const busy = useRef(false);
  const tableSize = useRef<number | null>(null);

  const run = useCallback(async <T,>(task: () => Promise<T>) => {
    if (busy.current) return null;
    busy.current = true;
    hints.current?.cancel();
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
    if (!busy.current && hand && !hand.result) await hints.current?.request(hand);
  }, [hand]);

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
      void hints.current?.request(settledHand);
    }
  }, []);

  const startHand = useCallback(async (playerCount?: number, blinds?: TrainingBlinds) => run(async () => {
    setAnalysis(null);
    setActionReview(null);
    const next = await PokerApi.startHand(playerCount, blinds);
    if (tableSize.current !== null && tableSize.current !== next.players.length) setDecisionLog([]);
    tableSize.current = next.players.length;
    await applyState(next);
  }), [applyState, run]);

  const action = useCallback(async (actionType: ActionType, amount?: number) => run(async () => {
    if (!hand) return;
    try {
      const result = await TrainingApi.action(hand, actionType, amount);
      setActionReview(result.review);
      setDecisionLog((current) => [result.review, ...current].slice(0, 25));
      await applyState(result.state);
    } catch (cause) {
      // A lost response must not leave the UI offering a stale action again.
      try { await applyState(await PokerApi.getState()); } catch { /* Keep the original error. */ }
      throw cause;
    }
  }), [applyState, hand, run]);

  const advance = useCallback(async () => run(async () => {
    await applyState(await PokerApi.advance());
  }), [applyState, run]);

  useEffect(() => {
    void startHand();
    return () => hints.current?.cancel();
  }, [startHand]);

  return {
    analysis,
    actionReview,
    decisionLog,
    error,
    hand,
    isLoading,
    isAnalyzing,
    action,
    advance,
    analyze,
    clearError: () => setError(null),
    startHand,
  };
}
