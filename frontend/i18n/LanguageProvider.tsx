'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { translate, type Locale } from './translate';

const STORAGE_KEY = 'poker-language';
const LanguageContext = createContext({
  locale: 'ru' as Locale,
  t: <T,>(value: T): T => translate(value, 'ru'),
  setLocale: (() => {}) as (locale: Locale) => void,
});

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  // Match server HTML first, then restore this browser's language preference.
  const [locale, setLanguage] = useState<Locale>('ru');
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === 'en' || saved === 'ru' || saved === 'uk') {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setLanguage(saved);
      }
    } catch { /* Storage is optional. */ }
    const syncLanguage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && (event.newValue === 'en' || event.newValue === 'ru' || event.newValue === 'uk')) setLanguage(event.newValue);
    };
    window.addEventListener('storage', syncLanguage);
    return () => window.removeEventListener('storage', syncLanguage);
  }, []);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  const setLocale = useCallback((next: Locale) => {
    setLanguage(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* Storage is optional. */ }
  }, []);
  const t = useCallback(<T,>(value: T): T => translate(value, locale), [locale]);
  return <LanguageContext.Provider value={{ locale, setLocale, t }}>{children}</LanguageContext.Provider>;
}

export function useI18n() { return useContext(LanguageContext); }

export function LanguageSwitcher({ inline = false }: { inline?: boolean }) {
  const { locale, setLocale } = useI18n();
  return <div className={`language-toolbar${inline ? ' language-toolbar-inline' : ''}`}><label htmlFor="poker-language">{locale === 'en' ? 'Language' : locale === 'uk' ? 'Мова' : 'Язык'}</label><select id="poker-language" value={locale} onChange={event => setLocale(event.target.value as Locale)}><option value="en" lang="en">EN</option><option value="ru" lang="ru">RU</option><option value="uk" lang="uk">UA</option></select></div>;
}
