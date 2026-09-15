import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import ChatPanel from '../components/ChatPanel';
import MapView from '../components/MapView';
import EvidencePanel from '../components/EvidencePanel';
import LanguageToggle from '../components/LanguageToggle';
import './ChatApp.css';

export default function ChatApp() {
  const { t } = useTranslation();
  const [mapData, setMapData] = useState(null);
  const [evidence, setEvidence] = useState(null);

  const handleResponse = (data) => {
    if (data.map_data) setMapData(data.map_data);
    if (data.evidence) setEvidence(data.evidence);
  };

  return (
    <div className="app-container">
      {/* Top header bar */}
      <header className="app-header">
        <div className="header-brand">
          <Link to="/">
            <span className="header-logo">🐋</span>
            <h1>{t('chat.title')}</h1>
          </Link>
          <span className="header-tagline">{t('chat.tagline')}</span>
        </div>
        <div className="header-badges">
          <span className="badge badge-sih">SIH 2026</span>
          <span className="badge badge-isro">ISRO</span>
          <LanguageToggle />
          <Link to="/" className="header-home-link">
            {t('nav.home')}
          </Link>
        </div>
      </header>

      {/* 3-panel layout */}
      <main className="app-main">
        <section className="panel panel-chat">
          <ChatPanel onResponse={handleResponse} />
        </section>

        <section className="panel panel-map">
          <MapView mapData={mapData} />
        </section>

        <section className="panel panel-evidence">
          <EvidencePanel evidence={evidence} />
        </section>
      </main>
    </div>
  );
}
