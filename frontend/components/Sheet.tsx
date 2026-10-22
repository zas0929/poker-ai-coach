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
      <header className="sheet-heading"><h2 id={headingId}>{title}</h2><button type="button" onClick={onClose} aria-label={t('Close')}>×</button></header>
      {open ? children : null}
    </div>
  </dialog>;
}
