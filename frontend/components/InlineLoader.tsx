'use client';
import { useI18n } from '@/i18n/LanguageProvider';

export default function InlineLoader() {
  const { t } = useI18n();
  return <span className="inline-loader" role="status" aria-label={t('Calculating…')}><span aria-hidden="true" /></span>;
}
