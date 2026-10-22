'use client';

import { useEffect, useId, useRef, type ReactNode } from 'react';
import { useI18n } from '@/i18n/LanguageProvider';

/** Native modal supplies focus trapping, Escape and focus restoration. */
export default function Sheet({ open, title, onClose, children }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  const { t } = useI18n();
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open) {
      if (!element.open) element.showModal();
      const previous = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = previous;
        if (element.open) element.close();
      };
    }
    if (element.open) element.close();
  }, [open]);
  return <dialog ref={dialog} className="poker-sheet" aria-labelledby={headingId}
    onCancel={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="sheet-surface">
      <header className="sheet-heading"><h2 id={headingId}>{title}</h2><button type="button" className="sheet-close" onClick={onClose} aria-label={t('Close')} title={t('Close')}><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg></button></header>
      {open ? children : null}
    </div>
  </dialog>;
}
