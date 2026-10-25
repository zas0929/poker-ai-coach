'use client';
import { useI18n } from '@/i18n/LanguageProvider';

export default function TableVisibility({ value, disabled, onChange }: {
  value: 'private' | 'public'; disabled: boolean; onChange: (value: 'private' | 'public') => void;
}) {
  const { t } = useI18n();
  return <div className="table-visibility">
    <label htmlFor="table-visibility">{t('Table visibility')}</label>
    <div className="visibility-select">
      <span className="visibility-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
        {value === 'private' ? <><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></> : <><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/></>}
      </svg></span>
      <select id="table-visibility" value={value} disabled={disabled} aria-describedby="visibility-description" onChange={event => onChange(event.target.value as 'private' | 'public')}>
        <option value="private">{t('Private table')}</option><option value="public">{t('Public table')}</option>
      </select>
      <svg className="visibility-caret" aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m4 6 4 4 4-4"/></svg>
    </div>
    <p id="visibility-description">{t(value === 'private' ? 'Only people with the invitation or room code can find this table.' : 'Anyone can find this table in the public list and join a free seat.')}</p>
  </div>;
}
