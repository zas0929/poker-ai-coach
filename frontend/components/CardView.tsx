'use client';

import { memo } from 'react';

import { useI18n } from '@/i18n/LanguageProvider';
import type { Card, Rank } from '@/types/poker';

const suits = { spades: '♠', hearts: '♥', diamonds: '♦', clubs: '♣' };

function Court({ rank, suit }: { rank: Rank; suit: string }) {
  const figure = <g stroke="#20232a" strokeWidth=".7" strokeLinejoin="round">
    <path d="M3 30 10 21 28 21 37 31 32 39 8 39Z" fill="#b92430" />
    <path d="M9 25 17 21 24 39 17 39Z" fill="#e6bd55" />
    <path d="M24 22 30 25 22 39 17 39Z" fill="#284a6a" />
    <path d="m8 31 6-5 4 6-5 6Z m17-4 5 5-6 6-4-6Z" fill="#f0d577" />
    <path d="M13 9Q20 3 27 9L25 20 21 24 16 20Z" fill="#f5dfb7" />
    <path d="M13 11 16 10 16 18 19 21 16 19 13 15Z" fill="#20232a" />
    <path d="M16 13h2m4 0h2m-4 1-1 3h2m-3 2h5" fill="none" />
    {rank === 'J' ? <path d="M11 10Q17 0 28 5L30 10Z" fill="#284a6a" /> : <path d="m12 9-1-7 6 4 3-6 3 6 6-4-1 7Z" fill="#e6bd55" />}
    {rank === 'Q' ? <path d="M13 12q-7 7 0 11m14-11q7 7 0 11" fill="none" stroke="#20232a" strokeWidth="2" /> : null}
    <path d="M5 25 5 7M3 9l2-5 2 5" fill="none" stroke="#c9a448" strokeWidth="1.5" />
  </g>;
  return <svg className="card-art court-art" viewBox="0 0 40 60" aria-hidden="true">
    <rect x="1" y="1" width="38" height="58" rx="1" fill="#fffdf6" stroke="#cbb66e" strokeWidth=".8" />
    {figure}<g transform="translate(40 60) rotate(180)">{figure}</g>
    <path d="m14 30 6-5 6 5-6 5Z" fill="#fffdf6" stroke="#20232a" strokeWidth=".7" />
    <text x="20" y="33" textAnchor="middle" fontSize="14" fill="currentColor">{suit}</text>
  </svg>;
}

function CardView({ card, hidden = false, placeholder = false }: {
  card?: Card; hidden?: boolean; placeholder?: boolean;
}) {
  const { t } = useI18n();
  if (placeholder) return <div className="playing-card card-placeholder" role="img" aria-label={t('Undealt card')} />;
  if (!card || hidden) return <div className="playing-card card-back stars-back" role="img" aria-label={t('Hidden card')}>
    <svg className="card-back-art" viewBox="0 0 240 336" aria-hidden="true">
      <rect width="240" height="336" rx="12" fill="#f4f0d9" />
      <svg x="13" y="13" width="214" height="310" viewBox="0 0 214 310">
        <rect width="214" height="310" fill="#172546" />
        {Array.from({ length: 9 }, (_, row) => Array.from({ length: 6 }, (_, col) => (
          <g key={`${row}-${col}`} transform={`translate(${col * 48 - 24 + (row % 2) * 24} ${row * 41.57 - 12})`} fill="none" stroke="#f4f0d9" strokeWidth="1.3" strokeLinejoin="miter">
            <path d="M0 41.57 24 0 48 41.57ZM8 37 24 9.2 40 37ZM16 32.4 24 18.5 32 32.4Z" />
            <path d="M24 0H72L48 41.57ZM32 4.6H64L48 32.4ZM40 9.2H56L48 23.1Z" />
          </g>
        )))}
        {[false, true].map((flipped) => (
          <g key={String(flipped)} transform={flipped ? 'translate(107 232) rotate(180)' : 'translate(107 78)'}>
            <path d="M0-35 27 0 0 35-27 0Z" fill="#172546" stroke="#f4f0d9" strokeWidth="1.8" />
            <path d="M0-24C-5-16-19-9-19 1c0 10 12 13 19 5-1 7-4 12-10 16H10C4 18 1 13 0 6c7 8 19 5 19-5C19-9 5-16 0-24Z" fill="#f4f0d9" />
            <path d="m0-10 2.7 8.2h8.6L4.3 3.3 7 11.5 0 6.4-7 11.5-4.3 3.3-11.3-1.8h8.6Z" fill="#172546" />
          </g>
        ))}
      </svg>
    </svg>
  </div>;
  const suit = suits[card.suit];
  const red = card.suit === 'hearts' || card.suit === 'diamonds';
  const rank = card.rank === 'T' ? '10' : card.rank;
  const corner = <><b>{rank}</b><i>{suit}</i></>;
  return <div className={`playing-card stars-face ${red ? 'red-card' : ''}`} role="img" aria-label={`${rank} ${suit}`}>
    <span className="card-corner corner-top" aria-hidden="true">{corner}</span>
    <span className="card-corner corner-bottom" aria-hidden="true">{corner}</span>
    {['K', 'Q', 'J'].includes(card.rank) ? <Court rank={card.rank} suit={suit} /> : <svg className="card-art pip-art" viewBox="0 0 40 60" aria-hidden="true">
      <text x="20" y="43" fontSize="44" textAnchor="middle" fill="currentColor">{suit}</text>
    </svg>}
  </div>;
}

// Server snapshots replace card objects even when their rank and suit stay the same.
export default memo(CardView, (previous, next) =>
  previous.card?.rank === next.card?.rank &&
  previous.card?.suit === next.card?.suit &&
  Boolean(previous.hidden) === Boolean(next.hidden) &&
  Boolean(previous.placeholder) === Boolean(next.placeholder),
);
