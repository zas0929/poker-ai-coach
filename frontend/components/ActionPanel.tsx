'use client';

import { useId, useMemo, useState, type ReactNode } from 'react';
import { displayPlayer } from '@/i18n/translate';
import { useI18n } from '@/i18n/LanguageProvider';
import Sheet from '@/components/Sheet';
import type { ActionType, HandAnalysis, HandState } from '@/types/poker';

interface ActionPanelProps {
  viewerId?: string;
  trainingControls?: boolean;
  analysis: HandAnalysis | null;
  hand: HandState | null;
  isLoading: boolean;
  blocked?: boolean;
  waitingLabel?: string;
  onAction: (action: ActionType, amount?: number) => void;
  onAdvance: () => void;
  onAnalyze: () => void;
  onStartHand: () => void;
  tools?: ReactNode;
  betweenActions?: ReactNode;
  pausedActions?: ReactNode;
  secondsLeft?: number | null;
}

export default function ActionPanel({ viewerId = 'hero', trainingControls = true, analysis, hand,
  isLoading, blocked = false, waitingLabel, onAction, onAdvance, onAnalyze, onStartHand, tools, secondsLeft, betweenActions, pausedActions }: ActionPanelProps) {
  const { t } = useI18n();
  const inputId = useId();
  const errorId = useId();
  const [amountEntry, setAmountEntry] = useState<{ context: string; value: string } | null>(null);
  const [sizingContext, setSizingContext] = useState<string | null>(null);
  const currentPlayer = hand?.players.find((player) => player.id === hand.current_player_id);
  const viewer = hand?.players.find((player) => player.id === viewerId);
  const handEnded = Boolean(hand?.result || hand?.street === 'showdown');
  const canAct = Boolean(currentPlayer?.id === viewerId && !handEnded && !blocked);
  const betting = hand?.betting;
  const allows = (action: ActionType) => canAct && Boolean(betting?.legal_actions.includes(action));
  const canSize = allows('bet') || allows('raise');
  const sizedAction: ActionType = allows('bet') ? 'bet' : 'raise';
  const minimumAmount = (sizedAction === 'bet' ? betting?.min_bet : betting?.min_raise_to) ?? 1;
  const maximumAmount = betting?.max_raise_to ?? 0;
  const callAmount = betting?.call_amount ?? 0;
  const heroStack = viewer?.stack ?? 0;
  const actionClosed = Boolean(hand && hand.current_player_id === null && !handEnded);
  const highestBet = Math.max(0, ...(hand?.players.map((player) => player.current_bet) ?? []),
    hand?.street === 'preflop' ? hand.big_blind : 0);
  const amountContext = `${hand?.hand_id}:${hand?.street}:${hand?.history.length}:${hand?.current_player_id}`;
  const suggestedAmount = Math.min(maximumAmount, Math.max(minimumAmount,
    highestBet > 0 ? highestBet * 2 : Math.round((hand?.pot ?? 0) / 2)));
  const amountText = amountEntry?.context === amountContext ? amountEntry.value : String(suggestedAmount);
  const amount = Number(amountText);
  const setAmount = (value: string | number) => setAmountEntry({ context: amountContext, value: String(value) });
  const validAmount = amountText.trim() !== '' && Number.isInteger(amount) && amount >= minimumAmount && amount <= maximumAmount;
  const amountToPay = validAmount ? Math.max(0, amount - (viewer?.current_bet ?? 0)) : 0;
  const clampAmount = (value: number) => Math.min(maximumAmount, Math.max(minimumAmount, value));
  const open = sizingContext === amountContext && canSize && !isLoading;
  const quickAmounts = useMemo(() => {
    if (!hand) return [];
    if (highestBet > 0) return [
      { label: 'x2', value: highestBet * 2 },
      { label: 'x3', value: highestBet * 3 },
      // A pot-sized raise includes the call before raising the resulting pot.
      { label: 'Pot', value: highestBet + hand.pot + callAmount },
    ];
    return [
      { label: '1/2 pot', value: Math.round(hand.pot / 2) },
      { label: '2/3 pot', value: Math.round(hand.pot * 2 / 3) },
      { label: 'Pot', value: hand.pot },
    ];
  }, [hand, highestBet, callAmount]);

  const submit = (action: ActionType, value?: number) => {
    if (isLoading || !allows(action)) return;
    setSizingContext(null);
    onAction(action, value);
  };
  const isRecommended = (action: ActionType) => analysis?.recommended_action === action && canAct ? ' recommended-action' : '';
  const passiveAction = allows('check') ? 'check' : 'call';

  return <section className="control-panel action-dock" aria-label={t('Table actions')}>
    <div className="turn-strip">
      <strong role="status">{isLoading ? t('Sending…') : waitingLabel ?? t(handEnded ? 'Hand complete' : canAct ? 'Your turn' : actionClosed ? 'Action closed' : 'Waiting')}
        {!isLoading && !handEnded && currentPlayer && !canAct ? <span> · {displayPlayer(currentPlayer, t)}</span> : null}
      </strong>
      {secondsLeft !== null && secondsLeft !== undefined && !handEnded ? <span className={`dock-clock ${secondsLeft <= 10 ? 'urgent' : ''}`} role="timer" aria-label={t('Time remaining')}>{secondsLeft}s</span> : <span>{t('Stack')} <b>{heroStack}</b></span>}
    </div>
    {pausedActions ? <div className="hand-actions">{pausedActions}</div> : !hand || handEnded || actionClosed ? <div className="hand-actions">
      {trainingControls && (!hand || handEnded) ? <button className="primary-button" disabled={isLoading} onClick={onStartHand}>{t(hand ? 'Next hand' : 'New hand')}</button> : null}
      {trainingControls && actionClosed ? <button className="primary-button" disabled={isLoading} onClick={onAdvance}>{t('Advance')}</button> : null}
      {!trainingControls ? betweenActions : null}
    </div> : <div className="action-grid">
      <button className={`fold-action${isRecommended('fold')}`} disabled={!allows('fold') || isLoading} onClick={() => submit('fold')}>{t('Fold')}</button>
      <button className={`passive-action${isRecommended(passiveAction)}`} disabled={!allows(passiveAction) || isLoading} onClick={() => submit(passiveAction)}>
        {t(passiveAction === 'check' ? 'Check' : 'Call')}{passiveAction === 'call' ? <small>{callAmount}</small> : null}
      </button>
      <button className={`primary-button size-action${isRecommended(sizedAction)}`} disabled={!canSize || isLoading} onClick={() => setSizingContext(amountContext)} aria-haspopup="dialog">
        {t(sizedAction === 'bet' ? 'Bet' : 'Raise')}<small>{t('Choose amount')} ↗</small>
      </button>
    </div>}
    <div className="dock-tools">{tools}{trainingControls && hand && !handEnded ? <button disabled={isLoading} onClick={onAnalyze}>{t('Analyze')}</button> : null}</div>
    <Sheet open={open} title={t(sizedAction === 'bet' ? 'Bet size' : 'Raise to')} onClose={() => setSizingContext(null)}>
      <div className="bet-sheet">
        {secondsLeft !== null && secondsLeft !== undefined ? <p className={`sheet-timer ${secondsLeft <= 10 ? "urgent" : ""}`} role="timer">{t("Time remaining")}: {secondsLeft}s</p> : null}
        <p className="sheet-note">{t(sizedAction === 'bet' ? 'Choose your bet, then confirm.' : 'Total bet on this street. Choose an amount, then confirm.')}</p>
        <label className="bet-entry" htmlFor={inputId}><span>{t(sizedAction === 'bet' ? 'Bet size' : 'Raise to')}</span>
          <input autoFocus id={inputId} type="number" inputMode="numeric" min={minimumAmount} max={maximumAmount} step={1} value={amountText}
            aria-invalid={!validAmount} aria-describedby={!validAmount ? errorId : undefined} onChange={(event) => setAmount(event.target.value)} />
        </label>
        <label className="sr-only" htmlFor={`${inputId}-range`}>{t('Bet amount slider')}</label>
        <input id={`${inputId}-range`} type="range" min={minimumAmount} max={maximumAmount} step={1} value={validAmount ? amount : minimumAmount} onChange={(event) => setAmount(event.target.value)} />
        <div className="bet-limits"><span>{t('Min.')} {minimumAmount}</span><span>{t('Max.')} {maximumAmount}</span></div>
        <div className="quick-size-grid">{quickAmounts.map((preset) => <button type="button" key={preset.label} aria-pressed={validAmount && amount === clampAmount(preset.value)} onClick={() => setAmount(clampAmount(preset.value))}>{t(preset.label)}<small>{clampAmount(preset.value)}</small></button>)}</div>
        <p className="bet-payment">{t('To pay now')} <strong>{validAmount ? amountToPay : "—"}</strong> · {t('Stack')} {heroStack}</p>
        {!validAmount ? <p id={errorId} className="bet-error" role="alert">{t('Enter a whole number from {0} to {1}.').replace('{0}', String(minimumAmount)).replace('{1}', String(maximumAmount))}</p> : null}
        <div className="bet-confirm"><button type="button" onClick={() => setSizingContext(null)}>{t('Cancel')}</button><button className="primary-button" disabled={!validAmount || isLoading} onClick={() => submit(sizedAction, amount)}>{t(sizedAction === 'bet' ? 'Bet' : 'Raise to')} {validAmount ? amount : '—'}</button></div>
        <button className="all-in-choice" type="button" onClick={() => setAmount(maximumAmount)}>{t('All in')} · {maximumAmount} <span>{t('Select amount')}</span></button>
      </div>
    </Sheet>
  </section>;
}
