import messages from './messages.json';

export type Locale = 'ru' | 'uk';
const dictionary: Record<string, Record<Locale, string>> = messages;
const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const patterns = Object.entries(dictionary).filter(([key]) => /\{\d+\}/.test(key)).map(([key, value]) => ({
  regex: new RegExp(`^${key.split(/\{\d+\}/).map(escape).join('(.+?)')}$`), value,
}));

/** Translate presentation text only; API actions and saved records stay canonical. */
export function translate<T>(value: T, locale: Locale): T {
  if (typeof value !== 'string') return value;
  return translateText(value, locale) as T;
}

function translateText(value: string, locale: Locale, depth = 0): string {
  if (!value.trim() || depth > 6) return value;
  const leading = value.match(/^\s*/)?.[0] ?? '';
  const trailing = value.match(/\s*$/)?.[0] ?? '';
  const text = value.trim();
  const direct = dictionary[text]?.[locale];
  if (direct) return leading + direct + trailing;
  for (const [key, translated] of Object.entries(dictionary)) {
    if (key.endsWith('.') && !key.includes('{') && text.endsWith(' ' + key)) {
      return leading + translateText(text.slice(0, -key.length - 1), locale, depth + 1) + ' ' + translated[locale] + trailing;
    }
    if (key.endsWith('.') && !key.includes('{') && text.startsWith(key + ' ')) {
      return leading + translated[locale] + ' ' + translateText(text.slice(key.length + 1), locale, depth + 1) + trailing;
    }
  }
  for (const pattern of patterns) {
    const match = pattern.regex.exec(text);
    if (match) return leading + pattern.value[locale].replace(/\{(\d+)\}/g, (_, index) => translateText(match[Number(index) + 1], locale, depth + 1)) + trailing;
  }
  // Saved advice combines independently generated sentences and range labels.
  const sentences = text.split(/(?<=\.)\s+(?=[A-Z])/);
  if (sentences.length > 1) return leading + sentences.map(sentence => translateText(sentence, locale, depth + 1)).join(' ') + trailing;
  const parts = text.split(/( → |, | · |: )/);
  if (parts.length > 1) return leading + parts.map(part => translateText(part, locale, depth + 1)).join('') + trailing;
  if (text.endsWith('.')) {
    const stem = text.slice(0, -1);
    if (dictionary[stem]) return leading + dictionary[stem][locale] + '.' + trailing;
  }
  if (text.includes(' plus ')) return leading + text.split(' plus ').map(part => translateText(part, locale, depth + 1)).join(locale === 'uk' ? ' із дро: ' : ' с дро: ') + trailing;
  const raised = /^(bet|raise) to (\d+)$/.exec(text);
  if (raised) return leading + translateText(raised[1], locale, depth + 1) + ' до ' + raised[2] + trailing;
  const action = /^(small blind|big blind|all in|fold|check|call|bet|raise) (\d+)$/.exec(text);
  if (action) return leading + translateText(action[1], locale, depth + 1) + ' ' + action[2] + trailing;
  return value;
}

export function displayPlayer(player: { id: string; name: string } | undefined, t: <T>(value: T) => T, fallback = '-') {
  if (!player) return fallback;
  if (player.id === 'hero' && player.name === 'You') return t('You');
  if (player.id === 'villain' && player.name === 'Practice opponent') return t('Practice opponent');
  return player.name;
}
