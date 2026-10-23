import type { Metadata, Viewport } from 'next';
import './globals.css';
import './redesign.css';
import './cards-and-timer.css';
import './table-polish.css';
import PwaRegistration from '@/components/PwaRegistration';
import { TableSoundProvider } from '@/components/TableSoundProvider';
import { LanguageProvider } from '@/i18n/LanguageProvider';

export const metadata: Metadata = {
  title: 'Poker AI Coach',
  description: "Тренажёр решений в техасском холдеме",
  applicationName: 'Poker AI Coach',
  appleWebApp: { capable: true, title: 'Poker Coach', statusBarStyle: 'default' },
  icons: {
    icon: [{ url: '/icons/icon.svg', type: 'image/svg+xml' }],
    apple: [{ url: '/icons/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }],
  },
};

export const viewport: Viewport = { themeColor: '#101719', colorScheme: 'dark' };

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body><PwaRegistration /><LanguageProvider><TableSoundProvider>{children}</TableSoundProvider></LanguageProvider></body>
    </html>
  );
}

