'use client';

import { useI18n } from '@/i18n/LanguageProvider';
import type { RoomState } from '@/services/roomApi';

export default function RoomSession({ room }: { room: RoomState | null }) {
  const { t } = useI18n();
  const me = room?.members.find(member => member.player_id === room.viewer_id);
  return <section className="control-panel session-panel"><h2>{t('Session')}</h2>
    <p className="room-note">{t('Results include completed hands only. Approved top-ups are buy-ins, not winnings.')}</p>
    {room?.members.some(member => member.session_partial) ? <p className="room-note">{t('For older seats, results are counted from this update because earlier buy-in totals were not saved.')}</p> : null}
    <div className="room-session-list">{room?.members.map(member => {
      const buyIn = member.session_buy_in;
      const topUps = member.session_top_ups ?? 0;
      // Member stacks are settled between hands; live bets must not look like losses.
      const net = buyIn == null ? null : member.stack - buyIn - topUps;
      return <div className="room-session-player" key={member.player_id}>
        <strong>{member.name}{member === me ? ` (${t('You')})` : ''}</strong>
        <strong className={net != null && net < 0 ? 'session-loss' : 'session-profit'}>{net == null ? '—' : `${net > 0 ? '+' : ''}${net}`}</strong>
        <small>{t(member.session_partial ? 'Opening balance' : 'Initial buy-in')}: {buyIn ?? '—'} · {t('Approved top-ups')}: {topUps}</small>
        <small>{t('Settled stack')}: {member.stack}</small>
      </div>;
    })}</div>
    <p className="room-note">{t('Blinds')} {room?.settings.small_blind}/{room?.settings.big_blind}</p>
  </section>;
}
