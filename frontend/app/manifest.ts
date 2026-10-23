import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: '/', name: 'Poker AI Coach', short_name: 'Poker Coach',
    description: 'Тренажёр покера и приватные столы для игры с друзьями',
    lang: 'ru', start_url: '/', scope: '/', display: 'standalone',
    background_color: '#101719', theme_color: '#101719',
    icons: [
      { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
    shortcuts: [
      { name: 'Игра с друзьями', url: '/friends' },
      { name: 'Практика', url: '/practice' },
    ],
  };
}
