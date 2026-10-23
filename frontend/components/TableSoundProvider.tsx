'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useI18n } from '@/i18n/LanguageProvider';

const SoundContext = createContext<{ enabled: boolean; toggle: () => void; play: (kind: 'deal' | 'timer', count?: number) => void }>({ enabled: true, toggle: () => {}, play: () => {} });

export function TableSoundProvider({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState(true);
  const preference = useRef(true);
  const audio = useRef<AudioContext | null>(null);
  const master = useRef<GainNode | null>(null);
  const unlock = useCallback(() => {
    if (!preference.current || typeof window === 'undefined' || !('AudioContext' in window)) return;
    try {
      if (!audio.current) {
        audio.current = new AudioContext();
        master.current = audio.current.createGain();
        master.current.gain.value = .18;
        master.current.connect(audio.current.destination);
      }
      if (audio.current.state === 'suspended') void audio.current.resume().catch(() => {});
    } catch { /* Audio is optional on unsupported or restricted devices. */ }
  }, []);
  useEffect(() => {
    try {
      const saved = localStorage.getItem('poker-sound');
      if (saved === 'off') {
        preference.current = false;
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setEnabled(false);
      }
    } catch { /* Storage is optional. */ }
    window.addEventListener('pointerdown', unlock);
    window.addEventListener('keydown', unlock);
    return () => {
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
      if (audio.current) void audio.current.close().catch(() => {});
      audio.current = null; master.current = null;
    };
  }, [unlock]);
  const toggle = useCallback(() => {
    const next = !preference.current;
    preference.current = next; setEnabled(next);
    try { localStorage.setItem('poker-sound', next ? 'on' : 'off'); } catch { /* Optional. */ }
    if (next) unlock();
    if (master.current && audio.current) master.current.gain.setValueAtTime(next ? .18 : 0, audio.current.currentTime);
  }, [unlock]);
  const play = useCallback((kind: 'deal' | 'timer', count = 1) => {
    const context = audio.current, output = master.current;
    if (!preference.current || !context || !output || context.state !== 'running') return;
    try {
      const notes = kind === 'timer' ? 2 : Math.min(12, Math.max(1, count));
      for (let index = 0; index < notes; index++) {
        const at = context.currentTime + .01 + index * (kind === 'timer' ? .14 : .065);
        const oscillator = context.createOscillator(), gain = context.createGain();
        oscillator.type = kind === 'timer' ? 'sine' : 'triangle';
        oscillator.frequency.setValueAtTime(kind === 'timer' ? (index ? 1046 : 784) : 700, at);
        if (kind === 'deal') oscillator.frequency.exponentialRampToValueAtTime(180, at + .035);
        gain.gain.setValueAtTime(.001, at);
        gain.gain.exponentialRampToValueAtTime(kind === 'timer' ? .18 : .1, at + .006);
        gain.gain.exponentialRampToValueAtTime(.001, at + (kind === 'timer' ? .11 : .045));
        oscillator.connect(gain); gain.connect(output);
        oscillator.start(at); oscillator.stop(at + .13);
        oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
      }
    } catch { /* Never interrupt gameplay because of an audio error. */ }
  }, []);
  return <SoundContext.Provider value={{ enabled, toggle, play }}>{children}</SoundContext.Provider>;
}

export const useTableSound = () => useContext(SoundContext);

export function SoundToggle() {
  const { t } = useI18n();
  const { enabled, toggle } = useTableSound();
  const label = t(enabled ? 'Mute sounds' : 'Enable sounds');
  return <button type="button" className="sound-toggle" onClick={toggle} aria-label={label} title={label} aria-pressed={enabled}><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 5 6 9H3v6h3l5 4V5Z" />
    {enabled ? <><path d="M15 8a6 6 0 0 1 0 8" /><path d="M18 5a10 10 0 0 1 0 14" /></> : <><path d="m16 9 6 6" /><path d="m22 9-6 6" /></>}
  </svg></button>;
}
