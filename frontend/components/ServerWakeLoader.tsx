'use client';

import { useEffect, useState } from 'react';
import { useI18n } from '@/i18n/LanguageProvider';

export default function ServerWakeLoader({ active }: { active: boolean }) {
  return active ? <ServerWait /> : null;
}

function ServerWait() {
  const { t } = useI18n();
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <section className="server-wake-loader" role="status" aria-live="polite" aria-busy="true">
    <span className="server-wake-spinner" aria-hidden="true" />
    <div><strong>{t(seconds < 4 ? 'Connecting to the server…' : 'Waiting for the server to wake up…')}</strong>
      <p>{t('The first connection can take about a minute. We will connect automatically.')}</p></div>
  </section>;
}
