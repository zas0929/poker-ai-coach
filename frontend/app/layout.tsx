import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Poker AI Coach',
  description: "Texas Hold'em decision trainer",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

