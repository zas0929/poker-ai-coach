'use client';


import { displayPlayer } from '@/i18n/translate';
import { useI18n } from '@/i18n/LanguageProvider';
import type { HandState } from '@/types/poker';

interface HandHistoryProps {
  hand: HandState | null;
}

export default function HandHistory({ hand }: HandHistoryProps) {
  const { t } = useI18n();
  return (
    <section className="history-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{t("Hand Log")}</p>
          <h2>{t("Actions")}</h2>
        </div>
      </div>

      <ol className="history-list">
        {(hand?.history ?? []).map((action, index) => (
          <li key={`${action.player_id}-${action.action}-${index}`}>
            <span>{t(action.street)}</span>
            <strong>{displayPlayer(hand?.players.find((p) => p.id === action.player_id), t, action.player_id)}</strong>
            <em>
              {t(action.action)}
              {t(action.amount ? ` ${action.amount}` : '')}
            </em>
          </li>
        ))}
      </ol>
    </section>
  );
}

