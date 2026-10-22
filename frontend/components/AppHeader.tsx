'use client';

import type { ReactNode } from 'react';
import { SoundToggle } from '@/components/TableSoundProvider';
import { LanguageSwitcher } from '@/i18n/LanguageProvider';

export default function AppHeader({ children, afterLogo }: { children?: ReactNode; afterLogo?: ReactNode }) {
  return (
    <header className="play-header">
      <h1><span aria-hidden="true">♠</span> Poker AI Coach</h1>
      {afterLogo}
      <div className="play-header-controls">{children}<SoundToggle /><LanguageSwitcher inline /></div>
    </header>
  );
}
