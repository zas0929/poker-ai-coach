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
  if (!card || hidden) {
    return <div className="playing-card card-back" aria-label="Hidden card" />;
  }

  const isRed = card.suit === 'hearts' || card.suit === 'diamonds';

  return (
    <div className={`playing-card ${isRed ? 'red-card' : ''}`}>
      <span>{card.rank}</span>
      <strong>{suitLabels[card.suit]}</strong>
    </div>
  );
}

