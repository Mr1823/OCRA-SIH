import { useTranslation } from 'react-i18next';
import './LanguageToggle.css';

/**
 * "EN | தமிழ்" switcher. react-i18next-languagedetector already
 * persists the choice to localStorage (see src/i18n.js), so it's
 * remembered across sessions automatically.
 */
export default function LanguageToggle() {
  const { i18n } = useTranslation();
  const current = i18n.resolvedLanguage || i18n.language;

  return (
    <div className="lang-toggle" role="group" aria-label="Language">
      <button
        type="button"
        className={current === 'en' ? 'lang-toggle-active' : ''}
        onClick={() => i18n.changeLanguage('en')}
      >
        EN
      </button>
      <span className="lang-toggle-sep">|</span>
      <button
        type="button"
        className={current === 'ta' ? 'lang-toggle-active' : ''}
        onClick={() => i18n.changeLanguage('ta')}
      >
        தமிழ்
      </button>
    </div>
  );
}
