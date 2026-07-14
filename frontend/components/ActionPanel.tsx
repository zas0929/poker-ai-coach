import { useMemo, useState } from 'react';

import type { ActionType, HandState } from '@/types/poker';

interface ActionPanelProps {
  hand: HandState | null;
  isLoading: boolean;
  onAction: (action: ActionType, amount?: number) => void;
  onAdvance: () => void;
  onAnalyze: () => void;
  onStartHand: () => void;
}

export default function ActionPanel({
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

  const callAmount = useMemo(() => {
    if (!hand || !currentPlayer) {
      return 0;
    }
    const highestBet = Math.max(...hand.players.map((player) => player.current_bet));
    return Math.max(highestBet - currentPlayer.current_bet, 0);
  }, [hand, currentPlayer]);

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

      <div className="amount-control">
        <label htmlFor="bet-amount">Bet target</label>
        <input
          id="bet-amount"
          min={1}
          type="number"
          value={amount}
          onChange={(event) => setAmount(Number(event.target.value))}
        />
      </div>

      <div className="action-grid">
        <button disabled={!canAct || isLoading} onClick={() => onAction('fold')}>
          Fold
        </button>
        <button disabled={!canAct || isLoading || callAmount > 0} onClick={() => onAction('check')}>
          Check
        </button>
        <button disabled={!canAct || isLoading || callAmount === 0} onClick={() => onAction('call')}>
          Call {callAmount || ''}
        </button>
        <button disabled={!canAct || isLoading || callAmount > 0} onClick={() => onAction('bet', amount)}>
          Bet
        </button>
        <button disabled={!canAct || isLoading} onClick={() => onAction('raise', amount)}>
          Raise
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
