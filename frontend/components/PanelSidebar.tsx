'use client';

import { useSyncExternalStore, type ReactNode } from 'react';
import Sheet from './Sheet';

const query = '(max-width: 760px)';
const subscribe = (callback: () => void) => {
  const media = window.matchMedia(query);
  media.addEventListener('change', callback);
  return () => media.removeEventListener('change', callback);
};
const getSnapshot = () => window.matchMedia(query).matches;
const getServerSnapshot = () => false;

export default function PanelSidebar({ panels, active, onClose, collapseOnMobile = true, notice }: {
  panels: { id: string; title: string; content: ReactNode }[];
  active: string | null; onClose: () => void; collapseOnMobile?: boolean; notice?: ReactNode;
}) {
  const mobile = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const selected = panels.find((panel) => panel.id === active);
  if (mobile && collapseOnMobile) {
    return <Sheet open={Boolean(selected)} title={selected?.title ?? ''} onClose={onClose}>{notice}{selected?.content}</Sheet>;
  }
  return <aside className="side-column">{panels.map((panel) => <div key={panel.id} className="sidebar-section">{panel.content}</div>)}</aside>;
}
