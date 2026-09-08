import { useState } from 'react';
import './EvidencePanel.css';

function CollapsibleSection({ title, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={`evidence-section ${open ? 'open' : ''}`}>
      <button className="section-header" onClick={() => setOpen(!open)}>
        <span className="section-title">{title}</span>
        <span className="section-chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && <div className="section-content">{children}</div>}
    </div>
  );
}

function DataRow({ label, value, unit = '' }) {
  if (value === undefined || value === null) return null;
  return (
    <div className="data-row">
      <span className="data-label">{label}</span>
      <span className="data-value">
        {typeof value === 'number' ? value.toFixed(1) : String(value)}
        {unit && <span className="data-unit"> {unit}</span>}
      </span>
    </div>
  );
}

function VerdictBadge({ verdict }) {
  const config = {
    safe: { emoji: '✅', color: '#4caf50', label: 'SAFE' },
    caution: { emoji: '⚠️', color: '#ff9800', label: 'CAUTION' },
    unsafe: { emoji: '🚫', color: '#f44336', label: 'UNSAFE' },
  };
  const v = config[verdict] || config.caution;
  return (
    <span className="verdict-badge" style={{ borderColor: v.color, color: v.color }}>
      {v.emoji} {v.label}
    </span>
  );
}

export default function EvidencePanel({ evidence }) {
  if (!evidence || Object.keys(evidence).length === 0) {
    return (
      <div className="evidence-panel">
        <div className="evidence-header">
          <h3>📋 Evidence Trail</h3>
        </div>
        <div className="evidence-empty">
          <p>Ask a question to see the reasoning trail here.</p>
          <p className="evidence-hint">
            ORCA shows which agents ran, what data was used, and why it reached
            its conclusion.
          </p>
        </div>
      </div>
    );
  }

  const {
    intent,
    agents_invoked = [],
    data_source,
    data_timestamp,
    query_timestamp,
    location = {},
    conditions_summary = {},
    risk_assessment,
    pfz_analysis,
    alerts,
  } = evidence;

  const ocean = conditions_summary.ocean || {};
  const weather = conditions_summary.weather || {};
  const tide = conditions_summary.tide || {};

  const intentLabels = {
    assess_sea_safety: '🛡️ Sea Safety Assessment',
    find_nearest_pfz: '🐟 Fishing Zone Discovery',
    check_alerts: '🌀 Weather Alert Check',
  };

  return (
    <div className="evidence-panel">
      <div className="evidence-header">
        <h3>📋 Evidence Trail</h3>
        <span className="evidence-subtitle">Why this answer?</span>
      </div>

      <div className="evidence-body">
        {/* Intent & Agents */}
        <div className="evidence-meta">
          <div className="meta-intent">{intentLabels[intent] || intent}</div>
          <div className="meta-agents">
            {agents_invoked.map((a, i) => (
              <span key={i} className="agent-tag">{a}</span>
            ))}
          </div>
          <div className="meta-source">
            <span className="source-badge">{data_source || 'mock'}</span>
            {data_timestamp && (
              <span className="timestamp">
                Data: {new Date(data_timestamp).toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>

        {/* Risk Assessment (safety queries) */}
        {risk_assessment && (
          <CollapsibleSection title="Risk Assessment" defaultOpen={true}>
            <div className="risk-summary">
              <VerdictBadge verdict={risk_assessment.verdict} />
              <span className="risk-score">
                Score: {risk_assessment.risk_score}/100
              </span>
            </div>
            {risk_assessment.thresholds_applied &&
              Object.entries(risk_assessment.thresholds_applied).map(
                ([param, info]) => (
                  <div key={param} className="threshold-row">
                    <span className="threshold-param">{param}</span>
                    <span className="threshold-value">
                      {info.value !== undefined
                        ? typeof info.value === 'number'
                          ? info.value.toFixed(1)
                          : info.value
                        : '?'}
                    </span>
                    <span
                      className={`threshold-status status-${info.status || 'unknown'}`}
                    >
                      {info.status || '?'}
                    </span>
                  </div>
                ),
              )}
          </CollapsibleSection>
        )}

        {/* PFZ Analysis */}
        {pfz_analysis && (
          <CollapsibleSection title="PFZ Analysis" defaultOpen={true}>
            <DataRow
              label="Local SST"
              value={pfz_analysis.current_location_sst}
              unit="°C"
            />
            <DataRow
              label="Local Chlorophyll"
              value={pfz_analysis.current_location_chlorophyll}
              unit="mg/m³"
            />
            <DataRow
              label="Zones Found"
              value={pfz_analysis.total_zones}
            />
            <DataRow
              label="Viable Zones"
              value={pfz_analysis.viable_zones}
            />
          </CollapsibleSection>
        )}

        {/* Alerts */}
        {alerts && (
          <CollapsibleSection title="Active Alerts" defaultOpen={true}>
            {alerts.alert_count === 0 ? (
              <p className="no-alerts">✅ No active alerts</p>
            ) : (
              alerts.active_alerts?.map((a, i) => (
                <div key={i} className="alert-card">
                  <div className="alert-title">{a.title || 'Alert'}</div>
                  <div className="alert-meta">
                    <span className={`alert-severity sev-${a.severity}`}>
                      {a.severity?.toUpperCase()}
                    </span>
                    <span className="alert-type">{a.type}</span>
                  </div>
                  <p className="alert-message">{a.message}</p>
                </div>
              ))
            )}
          </CollapsibleSection>
        )}

        {/* Ocean Conditions */}
        <CollapsibleSection title="Ocean Conditions">
          <DataRow label="SST" value={ocean.sst_celsius} unit="°C" />
          <DataRow
            label="Chlorophyll"
            value={ocean.chlorophyll_mg_m3}
            unit="mg/m³"
          />
          <DataRow
            label="Wave Height"
            value={ocean.wave_height_m}
            unit="m"
          />
          <DataRow
            label="Wave Period"
            value={ocean.wave_period_s}
            unit="s"
          />
        </CollapsibleSection>

        {/* Weather */}
        <CollapsibleSection title="Weather Conditions">
          <DataRow
            label="Wind Speed"
            value={weather.wind_speed_kmh}
            unit="km/h"
          />
          <DataRow label="Wind Direction" value={weather.wind_direction} />
          <DataRow
            label="Visibility"
            value={weather.visibility_km}
            unit="km"
          />
          <DataRow
            label="Temperature"
            value={weather.air_temperature_celsius}
            unit="°C"
          />
          <DataRow label="Humidity" value={weather.humidity_pct} unit="%" />
          <DataRow label="Condition" value={weather.condition} />
        </CollapsibleSection>

        {/* Tide */}
        {tide && Object.keys(tide).length > 0 && (
          <CollapsibleSection title="Tide Information">
            <DataRow label="Current" value={tide.current} />
            <DataRow label="Next Change" value={tide.next_change} />
            <DataRow label="Next Type" value={tide.next_type} />
            <DataRow
              label="Tidal Range"
              value={tide.tidal_range_m}
              unit="m"
            />
          </CollapsibleSection>
        )}

        {/* Location */}
        <CollapsibleSection title="Query Location">
          <DataRow label="Name" value={location.name} />
          <DataRow label="Latitude" value={location.lat} />
          <DataRow label="Longitude" value={location.lon} />
        </CollapsibleSection>
      </div>
    </div>
  );
}

