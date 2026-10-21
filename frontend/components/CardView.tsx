'use client';


import { useI18n } from '@/i18n/LanguageProvider';
import type { Card } from '@/types/poker';

const suitLabels = {
  spades: '♠',
  hearts: '♥',
  diamonds: '♦',
  clubs: '♣',
};

interface CardViewProps {
  card?: Card;
  hidden?: boolean;
}

export default function CardView({ card, hidden = false }: CardViewProps) {
  const { t } = useI18n();
  if (!card || hidden) {
    return <div className="playing-card card-back" aria-label={t("Hidden card")} />;
  }

  const isRed = card.suit === 'hearts' || card.suit === 'diamonds';

  return (
    <div className={`playing-card ${isRed ? 'red-card' : ''}`}>
      <span>{t(card.rank)}</span>
      <strong>{t(suitLabels[card.suit])}</strong>
    </div>
  );
}

