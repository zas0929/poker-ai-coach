'use client';
import { useI18n } from '@/i18n/LanguageProvider';

export interface PublicTable {
  code: string; players: number; small_blind: number; big_blind: number; starting_stack: number;
  can_join: boolean; hand_in_progress?: boolean; seats_available?: number;
}
export default function PublicTables({ tables, loading, error, onRefresh }: {
  tables: PublicTable[]; loading: boolean; error: boolean; onRefresh: () => void;
}) {
  const { t } = useI18n();
  return <section className="public-tables" aria-label={t('Public tables')} aria-busy={loading}>
    <header className="public-tables-heading"><div><h3>{t('Public tables')} <span>{tables.length}</span></h3><p>{t('Pick a table. Join during a hand and play from the next deal.')}</p></div>
      <button type="button" className="table-list-refresh" onClick={onRefresh} disabled={loading} aria-label={t('Refresh tables')} title={t('Refresh tables')}><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1"/></svg></button>
    </header>
    {error ? <p className="public-tables-empty" role="status">{t('Could not load public tables.')}</p> : !tables.length ? <div className="public-tables-empty" role="status"><span aria-hidden="true">♠</span><strong>{t(loading ? 'Loading tables…' : 'No public tables yet.')}</strong><p>{t('Create a public table to invite more players.')}</p></div> : <ul className="public-table-list">{tables.map(table => {
      const available = table.seats_available ?? Math.max(0,6-table.players);
      return <li key={table.code}><article className={`public-table-card ${!table.can_join ? 'table-full' : ''}`}>
        <div className="public-table-title"><span className="public-table-emblem" aria-hidden="true">♠</span><h4>{t('Room')} <b>{table.code}</b></h4><span className={`table-status ${table.hand_in_progress ? 'table-status-live' : ''}`}>{t(table.hand_in_progress ? 'Hand in progress' : 'Between hands')}</span></div>
        <div className="public-table-stats"><div><span>{t('Players')}</span><strong>{table.players}<small>/6</small></strong><span className="table-seat-dots" aria-hidden="true">{Array.from({length:6},(_,i)=><i key={i} className={i<table.players ? 'taken' : ''}/>)}</span></div><div><span>{t('Blinds')}</span><strong>{table.small_blind}<small> / </small>{table.big_blind}</strong></div><div><span>{t('Default buy-in')}</span><strong>{table.starting_stack}</strong></div></div>
        <footer><span>{t(table.can_join ? '{0} seats available' : 'No free seats').replace('{0}', String(available))}</span><a href={table.can_join ? `/friends?room=${table.code}` : undefined} aria-disabled={!table.can_join} className="public-table-join">{t(table.can_join ? table.hand_in_progress ? 'Join next hand' : 'Join room' : 'Table full')} <span aria-hidden="true">↗</span></a></footer>
      </article></li>;
    })}</ul>}
  </section>;
}
