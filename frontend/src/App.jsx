import { useState } from 'react';
import ChatPanel from './components/ChatPanel';
import MapView from './components/MapView';
import EvidencePanel from './components/EvidencePanel';
import './App.css';

export default function App() {
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
          <span className="header-logo">🐋</span>
          <h1>ORCA</h1>
          <span className="header-tagline">
            Marine EcOsystem Reasoning with Collaborative Agents
          </span>
        </div>
        <div className="header-badges">
          <span className="badge badge-sih">SIH 2026</span>
          <span className="badge badge-isro">ISRO</span>
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
