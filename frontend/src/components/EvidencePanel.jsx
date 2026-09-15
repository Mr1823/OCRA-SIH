import { useState } from 'react';
import { useTranslation } from 'react-i18next';
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

function VerdictBadge({ verdict, t }) {
  const config = {
    safe: { emoji: '✅', color: '#4caf50' },
    caution: { emoji: '⚠️', color: '#ff9800' },
    unsafe: { emoji: '🚫', color: '#f44336' },
  };
  const v = config[verdict] || config.caution;
  const label = t(`evidence.verdict.${verdict}`, { defaultValue: t('evidence.verdict.caution') });
  return (
    <span className="verdict-badge" style={{ borderColor: v.color, color: v.color }}>
      {v.emoji} {label}
    </span>
  );
}

// Backend threshold param keys (risk_assessment.py) → evidence.fields.* translation keys
const THRESHOLD_PARAM_LABEL_KEYS = {
  wave_height: 'waveHeight',
  wind_speed: 'windSpeed',
  visibility: 'visibility',
  alerts: 'sections.activeAlerts',
};

export default function EvidencePanel({ evidence }) {
  const { t } = useTranslation();

  if (!evidence || Object.keys(evidence).length === 0) {
    return (
      <div className="evidence-panel">
        <div className="evidence-header">
          <h3>{t('evidence.title')}</h3>
        </div>
        <div className="evidence-empty">
          <p>{t('evidence.emptyPrompt')}</p>
          <p className="evidence-hint">{t('evidence.emptyHint')}</p>
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

  return (
    <div className="evidence-panel">
      <div className="evidence-header">
        <h3>{t('evidence.title')}</h3>
        <span className="evidence-subtitle">{t('evidence.subtitle')}</span>
      </div>

      <div className="evidence-body">
        {/* Intent & Agents */}
        <div className="evidence-meta">
          <div className="meta-intent">{t(`evidence.intents.${intent}`, { defaultValue: intent })}</div>
          <div className="meta-agents">
            {agents_invoked.map((a, i) => (
              <span key={i} className="agent-tag">{a}</span>
            ))}
          </div>
          <div className="meta-source">
            <span className="source-badge">{data_source || 'mock'}</span>
            {data_timestamp && (
              <span className="timestamp">
                {new Date(data_timestamp).toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>

        {/* Risk Assessment (safety queries) */}
        {risk_assessment && (
          <CollapsibleSection title={t('evidence.sections.riskAssessment')} defaultOpen={true}>
            <div className="risk-summary">
              <VerdictBadge verdict={risk_assessment.verdict} t={t} />
              <span className="risk-score">
                {t('evidence.score')}: {risk_assessment.risk_score}/100
              </span>
            </div>
            {risk_assessment.thresholds_applied &&
              Object.entries(risk_assessment.thresholds_applied).map(
                ([param, info]) => (
                  <div key={param} className="threshold-row">
                    <span className="threshold-param">
                      {t(`evidence.fields.${THRESHOLD_PARAM_LABEL_KEYS[param] || param}`, {
                        defaultValue: param,
                      })}
                    </span>
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
                      {t(`evidence.verdict.${info.status}`, { defaultValue: info.status || '?' })}
                    </span>
                  </div>
                ),
              )}
          </CollapsibleSection>
        )}

        {/* PFZ Analysis */}
        {pfz_analysis && (
          <CollapsibleSection title={t('evidence.sections.pfzAnalysis')} defaultOpen={true}>
            <DataRow
              label={t('evidence.fields.localSst')}
              value={pfz_analysis.current_location_sst}
              unit="°C"
            />
            <DataRow
              label={t('evidence.fields.localChlorophyll')}
              value={pfz_analysis.current_location_chlorophyll}
              unit="mg/m³"
            />
            <DataRow label={t('evidence.fields.zonesFound')} value={pfz_analysis.total_zones} />
            <DataRow label={t('evidence.fields.viableZones')} value={pfz_analysis.viable_zones} />
          </CollapsibleSection>
        )}

        {/* Alerts */}
        {alerts && (
          <CollapsibleSection title={t('evidence.sections.activeAlerts')} defaultOpen={true}>
            {alerts.alert_count === 0 ? (
              <p className="no-alerts">{t('evidence.noAlerts')}</p>
            ) : (
              alerts.active_alerts?.map((a, i) => (
                <div
                  key={i}
                  className={`alert-card ${alerts.data_is_synthetic ? 'alert-card-synthetic' : ''}`}
                >
                  {alerts.data_is_synthetic && (
                    <span className="synthetic-badge" title={t('evidence.syntheticAlertTooltip')}>
                      {t('evidence.syntheticAlertBadge')}
                    </span>
                  )}
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
        <CollapsibleSection title={t('evidence.sections.oceanConditions')}>
          <DataRow label={t('evidence.fields.sst')} value={ocean.sst_celsius} unit="°C" />
          <DataRow label={t('evidence.fields.chlorophyll')} value={ocean.chlorophyll_mg_m3} unit="mg/m³" />
          <DataRow label={t('evidence.fields.waveHeight')} value={ocean.wave_height_m} unit="m" />
          <DataRow label={t('evidence.fields.wavePeriod')} value={ocean.wave_period_s} unit="s" />
        </CollapsibleSection>

        {/* Weather */}
        <CollapsibleSection title={t('evidence.sections.weatherConditions')}>
          <DataRow label={t('evidence.fields.windSpeed')} value={weather.wind_speed_kmh} unit="km/h" />
          <DataRow label={t('evidence.fields.windDirection')} value={weather.wind_direction} />
          <DataRow label={t('evidence.fields.visibility')} value={weather.visibility_km} unit="km" />
          <DataRow label={t('evidence.fields.temperature')} value={weather.air_temperature_celsius} unit="°C" />
          <DataRow label={t('evidence.fields.humidity')} value={weather.humidity_pct} unit="%" />
          <DataRow label={t('evidence.fields.condition')} value={weather.condition} />
        </CollapsibleSection>

        {/* Tide */}
        {tide && Object.keys(tide).length > 0 && (
          <CollapsibleSection title={t('evidence.sections.tideInformation')}>
            <DataRow label={t('evidence.fields.current')} value={tide.current} />
            <DataRow label={t('evidence.fields.nextChange')} value={tide.next_change} />
            <DataRow label={t('evidence.fields.nextType')} value={tide.next_type} />
            <DataRow label={t('evidence.fields.tidalRange')} value={tide.tidal_range_m} unit="m" />
          </CollapsibleSection>
        )}

        {/* Location */}
        <CollapsibleSection title={t('evidence.sections.queryLocation')}>
          <DataRow label={t('evidence.fields.name')} value={location.name} />
          <DataRow label={t('evidence.fields.latitude')} value={location.lat} />
          <DataRow label={t('evidence.fields.longitude')} value={location.lon} />
        </CollapsibleSection>
      </div>
    </div>
  );
}
