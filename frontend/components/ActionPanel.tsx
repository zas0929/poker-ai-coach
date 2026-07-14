import { useEffect, useMemo, useState } from 'react';

import type { ActionType, HandAnalysis, HandState } from '@/types/poker';

interface ActionPanelProps {
  analysis: HandAnalysis | null;
  hand: HandState | null;
  isLoading: boolean;
  onAction: (action: ActionType, amount?: number) => void;
  onAdvance: () => void;
  onAnalyze: () => void;
  onStartHand: () => void;
}

export default function ActionPanel({
  analysis,
  hand,
  isLoading,
  onAction,
  onAdvance,
  onAnalyze,
  onStartHand,
}: ActionPanelProps) {
  const [amount, setAmount] = useState(30);
  const currentPlayer = hand?.players.find((player) => player.id === hand.current_player_id);
  const handEnded = Boolean(hand?.result || hand?.street === 'showdown');
  const canAct = Boolean(currentPlayer?.id === 'hero' && !handEnded);
  const actionClosed = Boolean(hand && hand.current_player_id === null && !handEnded);
  const recommendedAction = analysis?.recommended_action as ActionType | undefined;
  const highestBet = useMemo(() => {
    if (!hand) {
      return 0;
    }
    return Math.max(...hand.players.map((player) => player.current_bet));
  }, [hand]);

  const callAmount = useMemo(() => {
    if (!hand || !currentPlayer) {
      return 0;
    }
    return Math.max(highestBet - currentPlayer.current_bet, 0);
  }, [currentPlayer, highestBet, hand]);
  const heroStack = currentPlayer?.id === 'hero' ? currentPlayer.stack : 0;

  const suggestedAmount = useMemo(() => {
    if (!hand) {
      return 30;
    }

    if (highestBet > 0) {
      return Math.max(highestBet * 2, highestBet + hand.big_blind);
    }

    return Math.max(hand.big_blind, Math.round(hand.pot / 2));
  }, [hand, highestBet]);

  useEffect(() => {
    setAmount(suggestedAmount);
  }, [suggestedAmount]);

  const quickAmounts = useMemo(() => {
    if (!hand) {
      return [];
    }

    if (highestBet > 0) {
      return [
        { label: 'x2', value: Math.max(highestBet * 2, highestBet + hand.big_blind) },
        { label: 'x3', value: Math.max(highestBet * 3, highestBet + hand.big_blind) },
        { label: 'Pot', value: Math.max(highestBet + hand.pot, highestBet + hand.big_blind) },
      ];
    }

    return [
      { label: '1/2 pot', value: Math.max(hand.big_blind, Math.round(hand.pot / 2)) },
      { label: '2/3 pot', value: Math.max(hand.big_blind, Math.round((hand.pot * 2) / 3)) },
      { label: 'Pot', value: Math.max(hand.big_blind, hand.pot) },
    ];
  }, [hand, highestBet]);

  const buttonClass = (actionType: ActionType) =>
    recommendedAction === actionType && canAct ? 'recommended-action' : undefined;

  const goAllIn = () => {
    if (!currentPlayer || currentPlayer.id !== 'hero') {
      return;
    }

    if (callAmount >= currentPlayer.stack) {
      onAction('call');
      return;
    }

    if (highestBet > 0) {
      onAction('raise', currentPlayer.current_bet + currentPlayer.stack);
      return;
    }

    onAction('bet', currentPlayer.stack);
  };

  return (
    <section className="control-panel">
      <div className="turn-strip">
        <span>Turn</span>
        <strong>
          {currentPlayer?.id === 'villain'
            ? 'AI thinking'
            : currentPlayer?.name ?? (handEnded ? 'Hand complete' : 'Action closed')}
        </strong>
      </div>

      {handEnded ? (
        <button className="primary-button next-hand-button" disabled={isLoading} onClick={onStartHand}>
          Next hand
        </button>
      ) : null}

      {analysis ? (
        <div className="decision-strip">
          <span>
            Best <strong>{analysis.recommended_action}</strong>
          </span>
          <span>
            Equity <strong>{formatPercent(analysis.equity)}</strong>
          </span>
          <span>
            Req <strong>{formatPercent(analysis.required_equity)}</strong>
          </span>
          <span>
            EV <strong>{analysis.ev_call}</strong>
          </span>
        </div>
      ) : null}

      <div className="amount-control">
        <label htmlFor="bet-amount">{highestBet > 0 ? 'Raise to' : 'Bet size'}</label>
        <input
          id="bet-amount"
          min={1}
          type="number"
          value={amount}
          onChange={(event) => setAmount(Number(event.target.value))}
        />
      </div>

      <div className="quick-size-grid">
        {quickAmounts.map((preset) => (
          <button
            key={preset.label}
            disabled={!canAct || isLoading}
            type="button"
            onClick={() => {
              setAmount(preset.value);
              onAction(highestBet > 0 ? 'raise' : 'bet', preset.value);
            }}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="action-grid">
        <button className={buttonClass('fold')} disabled={!canAct || isLoading} onClick={() => onAction('fold')}>
          Fold
        </button>
        <button className={buttonClass('check')} disabled={!canAct || isLoading || callAmount > 0} onClick={() => onAction('check')}>
          Check
        </button>
        <button className={buttonClass('call')} disabled={!canAct || isLoading || callAmount === 0} onClick={() => onAction('call')}>
          Call {callAmount || ''}
        </button>
        <button className={buttonClass('bet')} disabled={!canAct || isLoading || callAmount > 0} onClick={() => onAction('bet', amount)}>
          Bet
        </button>
        <button className={buttonClass('raise')} disabled={!canAct || isLoading} onClick={() => onAction('raise', amount)}>
          Raise
        </button>
        <button className="all-in-button" disabled={!canAct || isLoading || heroStack <= 0} onClick={goAllIn}>
          All in
        </button>
      </div>

      <div className="secondary-actions">
        <button disabled={!actionClosed || isLoading} onClick={onAdvance}>
          Advance
        </button>
        <button disabled={!hand || isLoading} onClick={onAnalyze}>
          Analyze
        </button>
      </div>
    </section>
  );
}

function formatPercent(value: number) {
  return `${Math.round(value * 1000) / 10}%`;
}
