'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useI18n } from '@/i18n/LanguageProvider';

export default function InfoTip({ label, explanation }: { label: string; explanation: string }) {
  const { t } = useI18n();
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLSpanElement>(null);
  const pinned = useRef(false);
  const [open, setOpen] = useState(false);

  const hide = () => { tip.current?.hidePopover(); pinned.current = false; };
  const show = () => {
    const element = tip.current;
    const anchor = button.current;
    if (!element || !anchor) return;
    element.showPopover();
    const rect = anchor.getBoundingClientRect();
    const width = document.documentElement.clientWidth;
    const height = window.innerHeight;
    const left = Math.max(12, Math.min(rect.left, width - element.offsetWidth - 12));
    const below = rect.bottom + 8;
    const top = below + element.offsetHeight <= height - 12 ? below : Math.max(12, rect.top - element.offsetHeight - 8);
    element.style.left = `${left}px`;
    element.style.top = `${top}px`;
  };

  useEffect(() => {
    if (!open) return;
    const close = () => { tip.current?.hidePopover(); pinned.current = false; };
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
    return () => {
      window.removeEventListener('resize', close);
      window.removeEventListener('scroll', close, true);
    };
  }, [open]);

  return <span className="metric-label">{t(label)}<span className="info-tip"
    onPointerEnter={event => { if (event.pointerType === 'mouse') show(); }}
    onPointerLeave={() => { if (!pinned.current) hide(); }}>
    <button ref={button} type="button" aria-label={t('Explain {0}').replace('{0}', t(label))}
      aria-expanded={open} aria-controls={id} aria-describedby={open ? id : undefined}
      onFocus={show} onBlur={() => { if (!pinned.current) hide(); }}
      onClick={() => { if (pinned.current) hide(); else { pinned.current = true; show(); } }}>?</button>
    <span ref={tip} id={id} className="info-tip-content" role="tooltip" popover="auto"
      onToggle={event => { const visible = event.newState === 'open'; setOpen(visible); if (!visible) pinned.current = false; }}>{t(explanation)}</span>
  </span></span>;
}
