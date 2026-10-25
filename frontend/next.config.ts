import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  distDir: process.env.POKER_NEXT_DIST_DIR ?? '.next',
  async headers() {
    return [{ source: '/sw.js', headers: [
      { key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' },
      { key: 'Content-Type', value: 'application/javascript; charset=utf-8' },
      { key: 'Service-Worker-Allowed', value: '/' },
    ] }];
  },
};

export default nextConfig;

