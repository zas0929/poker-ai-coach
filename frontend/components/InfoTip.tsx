import { useI18n } from '@/i18n/LanguageProvider';

export default function InfoTip({ label, explanation }: { label: string; explanation: string }) {
  const { t } = useI18n();
  return <span className="metric-label">{t(label)}<details className="info-tip"><summary aria-label={t('Explain {0}').replace('{0}', t(label))}>?</summary><span role="note">{t(explanation)}</span></details></span>;
}
