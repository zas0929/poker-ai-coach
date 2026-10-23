'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useI18n } from '@/i18n/LanguageProvider';

export type TableSound = 'deal' | 'timer' | 'check' | 'chips' | 'win' | 'reveal';

const SoundContext = createContext<{ enabled: boolean; toggle: () => void; play: (kind: TableSound, count?: number) => void }>({ enabled: true, toggle: () => {}, play: () => {} });

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
  const play = useCallback((kind: TableSound, count = 1) => {
    const context = audio.current, output = master.current;
    if (!preference.current || !context || !output || context.state !== 'running') return;
    try {
      const notes = kind === 'timer' ? 2 : kind === 'check' ? 2 : kind === 'win' ? 8 : Math.min(12, Math.max(1, count));
      for (let index = 0; index < notes; index++) {
        const at = context.currentTime + .01 + index * (kind === 'timer' ? .14 : kind === 'check' ? .09 : .055);
        const gain = context.createGain();
        gain.connect(output);
        if (kind === 'deal' || kind === 'reveal' || kind === 'chips' || kind === 'win') {
          // Short filtered noise gives cards a paper swish and chips a crisp rattle.
          const duration = kind === 'reveal' ? .12 : .065;
          const buffer = context.createBuffer(1, Math.ceil(context.sampleRate * duration), context.sampleRate);
          const data = buffer.getChannelData(0);
          for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
          const noise = context.createBufferSource(), filter = context.createBiquadFilter();
          noise.buffer = buffer;
          filter.type = 'bandpass';
          filter.frequency.value = kind === 'deal' || kind === 'reveal' ? 1600 : 3800 + index * 80;
          filter.Q.value = kind === 'deal' || kind === 'reveal' ? .7 : 3;
          gain.gain.setValueAtTime(.001, at);
          gain.gain.exponentialRampToValueAtTime(.5, at + .004);
          gain.gain.exponentialRampToValueAtTime(.001, at + duration);
          noise.connect(filter); filter.connect(gain);
          noise.start(at); noise.stop(at + duration);
          noise.onended = () => { noise.disconnect(); filter.disconnect(); gain.disconnect(); };
        } else {
          const oscillator = context.createOscillator();
          oscillator.type = 'sine';
          oscillator.frequency.setValueAtTime(kind === 'timer' ? (index ? 1046 : 784) : 155, at);
          if (kind === 'check') oscillator.frequency.exponentialRampToValueAtTime(65, at + .065);
          gain.gain.setValueAtTime(.001, at);
          gain.gain.exponentialRampToValueAtTime(kind === 'timer' ? .18 : .65, at + .004);
          gain.gain.exponentialRampToValueAtTime(.001, at + (kind === 'timer' ? .11 : .07));
          oscillator.connect(gain);
          oscillator.start(at); oscillator.stop(at + .13);
          oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
        }
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
