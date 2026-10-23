'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { tableAudioSamples } from '@/services/tableAudio';
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
      const notes = kind === 'timer' ? 2 : kind === 'check' ? 2 : kind === 'win' ? 5 : kind === 'chips' ? Math.min(4, Math.max(2, count * 2)) : Math.min(12, Math.max(1, count));
      for (let index = 0; index < notes; index++) {
        const at = context.currentTime + .01 + index * (kind === 'timer' ? .14 : kind === 'check' ? .09 : kind === 'win' || kind === 'chips' ? .095 : .085);
        const gain = context.createGain();
        gain.connect(output);
        if (kind === 'deal' || kind === 'reveal' || kind === 'chips' || kind === 'win') {
          const samples = tableAudioSamples(kind, context.sampleRate, index);
          const buffer = context.createBuffer(1, samples.length, context.sampleRate);
          buffer.getChannelData(0).set(samples);
          const source = context.createBufferSource();
          source.buffer = buffer;
          source.connect(gain);
          source.start(at);
          source.onended = () => { source.disconnect(); gain.disconnect(); };
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
