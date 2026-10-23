"use client";

import { useEffect, useRef } from 'react';
import { useI18n } from '@/i18n/LanguageProvider';

export default function Toast({ message, onDismiss, error = false }: {
  message: string; onDismiss: () => void; error?: boolean;
}) {
  const { t } = useI18n();
  const surface = useRef<HTMLDivElement>(null);
  const dismiss = useRef(onDismiss);
  useEffect(() => { dismiss.current = onDismiss; }, [onDismiss]);
  useEffect(() => {
    surface.current?.showPopover?.();
    const timer = setTimeout(() => dismiss.current(), 10000);
    return () => clearTimeout(timer);
  }, [message]);

  return <div ref={surface} popover="manual" className={`room-toast ${error ? 'room-toast-error' : ''}`} role={error ? 'alert' : 'status'}>
    <span>{message}</span><button type="button" aria-label={t('Dismiss')} onClick={onDismiss}>×</button>
  </div>;
}
