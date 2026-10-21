'use client';


import { displayPlayer } from '@/i18n/translate';
import { useI18n } from '@/i18n/LanguageProvider';
import { useMemo, useState } from 'react';

import type { ActionType, HandAnalysis, HandState } from '@/types/poker';

interface ActionPanelProps {
  viewerId?: string;
  trainingControls?: boolean;
  analysis: HandAnalysis | null;
  hand: HandState | null;
  isLoading: boolean;
  onAction: (action: ActionType, amount?: number) => void;
  onAdvance: () => void;
  onAnalyze: () => void;
  onStartHand: () => void;
}

export default function ActionPanel({
  viewerId = 'hero',
  trainingControls = true,
  analysis,
  hand,
  isLoading,
  onAction,
  onAdvance,
  onAnalyze,
  onStartHand,
}: ActionPanelProps) {
  const { t } = useI18n();
  const [amountEntry, setAmountEntry] = useState<{ context: string; value: number } | null>(null);
  const currentPlayer = hand?.players.find((player) => player.id === hand.current_player_id);
  const handEnded = Boolean(hand?.result || hand?.street === 'showdown');
  const canAct = Boolean(currentPlayer?.id === viewerId && !handEnded);
  const betting = hand?.betting;
  const allows = (action: ActionType) => canAct && Boolean(betting?.legal_actions.includes(action));
  const canSize = allows('bet') || allows('raise');
  const minimumAmount = betting?.min_raise_to ?? betting?.min_bet ?? 1;
  const maximumAmount = betting?.max_raise_to ?? 0;
  const actionClosed = Boolean(hand && hand.current_player_id === null && !handEnded);
  const recommendedAction = analysis?.recommended_action as ActionType | undefined;
  const highestBet = useMemo(() => {
    if (!hand) {
      return 0;
    }
    return Math.max(...hand.players.map((player) => player.current_bet));
  }, [hand]);

  const callAmount = betting?.call_amount ?? 0;
  const heroStack = currentPlayer?.id === viewerId ? currentPlayer.stack : 0;

  const suggestedAmount = useMemo(() => {
    if (!hand || maximumAmount === 0) return minimumAmount;
    const preferred = highestBet > 0
      ? Math.max(highestBet * 2, minimumAmount)
      : Math.max(minimumAmount, Math.round(hand.pot / 2));
    return Math.min(maximumAmount, preferred);
  }, [hand, highestBet, minimumAmount, maximumAmount]);

  const amountContext = `${hand?.hand_id}:${hand?.street}:${hand?.history.length}:${hand?.current_player_id}`;
  const amount = amountEntry?.context === amountContext ? amountEntry.value : suggestedAmount;
  const setAmount = (value: number) => setAmountEntry({ context: amountContext, value });
  const validAmount = Number.isInteger(amount) && amount >= minimumAmount && amount <= maximumAmount;

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
  const sizedAction: ActionType = highestBet > 0 ? 'raise' : 'bet';
  const clampAmount = (value: number) => Math.min(maximumAmount, Math.max(minimumAmount, value));
  const actionContext = callAmount > 0 ? `Facing ${callAmount}` : highestBet > 0 ? 'Matched pot' : 'Open action';

  const goAllIn = () => {
    if (!currentPlayer || currentPlayer.id !== viewerId) {
      return;
    }

    if (allows('raise')) {
      onAction('raise', maximumAmount);
    } else if (allows('bet')) {
      onAction('bet', maximumAmount);
    } else if (allows('call')) {
      onAction('call');
    }
  };

  return (
    <section className="control-panel">
      <div className="turn-strip">
        <div>
          <span>{t("Turn")}</span>
          <strong>
            {currentPlayer && currentPlayer.id !== viewerId
              ? t('{0} thinking').replace('{0}', displayPlayer(currentPlayer, t))
              : currentPlayer ? displayPlayer(currentPlayer, t) : t(handEnded ? 'Hand complete' : 'Action closed')}
          </strong>
        </div>
        <em>{t(handEnded ? 'Result ready' : `${actionContext} · Stack ${heroStack || '-'}`)}</em>
      </div>

      <div className="sizing-panel">
        <div className="amount-control">
          <label htmlFor="bet-amount">{t(highestBet > 0 ? 'Raise to' : 'Bet size')}</label>
          <input
            id="bet-amount"
            min={minimumAmount}
            max={maximumAmount}
            step={1}
            disabled={!canSize || isLoading}
            type="number"
            value={amount}
            onChange={(event) => setAmount(Number(event.target.value))}
          />
        </div>

        <div className="quick-size-grid">
          {quickAmounts.map((preset) => (
            <button
              key={preset.label}
              disabled={!canSize || isLoading}
              type="button"
              onClick={() => {
                const value = clampAmount(preset.value);
                setAmount(value);
                onAction(sizedAction, value);
              }}
            >
              {t(preset.label)}
            </button>
          ))}
        </div>
      </div>

      <div className="action-grid">
        <button className={buttonClass('fold')} disabled={!allows('fold') || isLoading} onClick={() => onAction('fold')}>{t("Fold")}</button>
        <button className={buttonClass('check')} disabled={!allows('check') || isLoading} onClick={() => onAction('check')}>{t("Check")}</button>
        <button className={buttonClass('call')} disabled={!allows('call') || isLoading} onClick={() => onAction('call')}>{t("Call ")}{t(callAmount || '')}
        </button>
        <button className={buttonClass('bet')} disabled={!allows('bet') || isLoading || !validAmount} onClick={() => onAction('bet', amount)}>{t("Bet")}</button>
        <button className={buttonClass('raise')} disabled={!allows('raise') || isLoading || !validAmount} onClick={() => onAction('raise', amount)}>{t("Raise")}</button>
        <button className="all-in-button" disabled={isLoading || (!canSize && !(allows('call') && callAmount === heroStack))} onClick={goAllIn}>{t("All in")}</button>
      </div>

      {trainingControls ? <div className="secondary-actions">
        <button className="primary-button next-hand-button" disabled={!handEnded || isLoading} onClick={onStartHand}>{t("Next hand")}</button>
        <button disabled={!actionClosed || isLoading} onClick={onAdvance}>{t("Advance")}</button>
        <button disabled={!hand || handEnded || isLoading} onClick={onAnalyze}>{t("Analyze")}</button>
      </div> : null}
    </section>
  );
}
