import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import OceanHero from '../components/three/OceanHero';
import Reveal from '../components/Reveal';
import ScrollProgress from '../components/ScrollProgress';
import LanguageToggle from '../components/LanguageToggle';
import './Landing.css';

const FEATURE_KEYS = ['safety', 'pfz', 'alerts', 'coverage'];
const FEATURE_ICONS = { safety: '🛡️', pfz: '🐟', alerts: '🌀', coverage: '📍' };
const DATA_SOURCE_KEYS = ['openMeteo', 'imd', 'copernicus', 'llm'];

export default function Landing() {
  const { t } = useTranslation();

  return (
    <div className="landing">
      <ScrollProgress />

      <nav className="landing-nav">
        <div className="landing-nav-brand">
          <span className="landing-nav-logo">🐋</span>
          <span className="landing-nav-name">ORCA</span>
        </div>
        <div className="landing-nav-right">
          <span className="badge badge-sih">SIH 2026</span>
          <span className="badge badge-isro">ISRO</span>
          <LanguageToggle />
          <Link to="/app" className="landing-nav-cta">
            {t('nav.openAssistant')}
          </Link>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="hero">
        <OceanHero />
        <div className="hero-glow" aria-hidden="true" />
        <div className="hero-content">
          <p className="hero-eyebrow">{t('landing.eyebrow')}</p>
          <h1 className="hero-title">{t('landing.title')}</h1>
          <p className="hero-title-sub">{t('landing.titleSub')}</p>
          <p className="hero-desc">{t('landing.heroDesc')}</p>
          <div className="hero-actions">
            <Link to="/app" className="btn-cta">
              {t('landing.askOrca')}
            </Link>
            <a href="#solution" className="btn-ghost">
              {t('landing.seeHowItWorks')}
            </a>
          </div>
        </div>
      </section>

      {/* ── Problem — asymmetric two-column ── */}
      <section className="section section-problem">
        <div className="grain-overlay" />
        <div className="section-inner problem-grid">
          <Reveal as="div" className="problem-heading-col">
            <span className="section-label">{t('landing.problem.label')}</span>
            <h2>{t('landing.problem.heading')}</h2>
          </Reveal>
          <Reveal as="div" className="problem-body-col" delay={120}>
            <p className="section-lead">{t('landing.problem.body1')}</p>
            <p className="section-lead">{t('landing.problem.body2')}</p>
          </Reveal>
        </div>
      </section>

      {/* ── Solution ── */}
      <section id="solution" className="section section-solution">
        <div className="section-inner">
          <Reveal>
            <span className="section-label">{t('landing.solution.label')}</span>
            <h2>{t('landing.solution.heading')}</h2>
            <p className="section-lead">{t('landing.solution.body')}</p>
          </Reveal>

          <Reveal delay={150} className="agent-flow">
            <div className="agent-node agent-node-entry">
              <span className="agent-node-label">{t('landing.solution.flow.question')}</span>
              <span className="agent-node-sub">{t('landing.solution.flow.questionSub')}</span>
            </div>
            <div className="agent-arrow">→</div>
            <div className="agent-node">
              <span className="agent-node-label">{t('landing.solution.flow.orchestrator')}</span>
              <span className="agent-node-sub">{t('landing.solution.flow.orchestratorSub')}</span>
            </div>
            <div className="agent-arrow">→</div>
            <div className="agent-node-group">
              <div className="agent-node">
                <span className="agent-node-label">{t('landing.solution.flow.oceanWeather')}</span>
              </div>
              <div className="agent-node">
                <span className="agent-node-label">{t('landing.solution.flow.riskAssessment')}</span>
              </div>
              <div className="agent-node">
                <span className="agent-node-label">{t('landing.solution.flow.pfzScoring')}</span>
              </div>
            </div>
            <div className="agent-arrow">→</div>
            <div className="agent-node agent-node-exit">
              <span className="agent-node-label">{t('landing.solution.flow.synthesis')}</span>
              <span className="agent-node-sub">{t('landing.solution.flow.synthesisSub')}</span>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="section section-features">
        <div className="section-inner">
          <Reveal>
            <span className="section-label">{t('landing.features.label')}</span>
            <h2>{t('landing.features.heading')}</h2>
          </Reveal>
          <div className="feature-grid">
            {FEATURE_KEYS.map((key, i) => (
              <Reveal as="div" className="feature-card" key={key} delay={i * 90}>
                <span className="feature-icon">{FEATURE_ICONS[key]}</span>
                <h3>{t(`landing.features.items.${key}.title`)}</h3>
                <p>{t(`landing.features.items.${key}.desc`)}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── Tech / Data credibility ── */}
      <section className="section section-tech">
        <div className="grain-overlay" />
        <div className="section-inner">
          <Reveal>
            <span className="section-label">{t('landing.tech.label')}</span>
            <h2>{t('landing.tech.heading')}</h2>
            <p className="section-lead">{t('landing.tech.body')}</p>
          </Reveal>
          <Reveal delay={120} className="data-source-list">
            {DATA_SOURCE_KEYS.map((key) => (
              <div className="data-source-row" key={key}>
                <span className="data-source-name">{t(`landing.tech.sources.${key}.name`)}</span>
                <span className="data-source-role">{t(`landing.tech.sources.${key}.role`)}</span>
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      {/* ── Final CTA ── */}
      <section className="section section-final-cta">
        <Reveal as="div" className="section-inner section-final-cta-inner">
          <h2>{t('landing.finalCta.heading')}</h2>
          <Link to="/app" className="btn-cta btn-cta-large">
            {t('nav.openAssistant')} →
          </Link>
        </Reveal>
      </section>

      <footer className="landing-footer">
        <div className="footer-badges">
          <span className="badge badge-sih">SIH 2026</span>
          <span className="badge badge-isro">ISRO Track</span>
        </div>
      </footer>
    </div>
  );
}
