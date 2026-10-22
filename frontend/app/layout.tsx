import type { Metadata } from 'next';
import './globals.css';
import './redesign.css';
import './cards-and-timer.css';
import './table-polish.css';
import { LanguageProvider } from '@/i18n/LanguageProvider';

export const metadata: Metadata = {
  title: 'Poker AI Coach',
  description: "Тренажёр решений в техасском холдеме",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body><LanguageProvider>{children}</LanguageProvider></body>
    </html>
  );
}

