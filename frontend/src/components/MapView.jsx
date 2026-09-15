import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './MapView.css';

// Fix Leaflet's default icon path issue with bundlers
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Color-coded circle marker icons
function createIcon(color) {
  // "blue" is the plain location pin — tied to the brand accent.
  // green/red/orange/cyan are the safety-verdict signal colors and are
  // deliberately left unchanged.
  const colorMap = {
    blue: '#0ea5e9',
    green: '#4caf50',
    red: '#f44336',
    orange: '#ff9800',
    cyan: '#00bcd4',
    yellow: '#ffeb3b',
  };

  const hex = colorMap[color] || colorMap.blue;

  return L.divIcon({
    className: 'custom-marker',
    html: `<div style="
      width: 24px; height: 24px;
      background: ${hex};
      border: 3px solid white;
      border-radius: 50%;
      box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    "></div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -14],
  });
}

// Component to update map view when data changes
function MapUpdater({ center, zoom }) {
  const map = useMap();
  const prevCenter = useRef(null);

  useEffect(() => {
    if (
      center &&
      (!prevCenter.current ||
        prevCenter.current[0] !== center[0] ||
        prevCenter.current[1] !== center[1])
    ) {
      map.flyTo(center, zoom, { duration: 1.2 });
      prevCenter.current = center;
    }
  }, [center, zoom, map]);

  return null;
}

// Default view: India's coastline
const DEFAULT_CENTER = [15.0, 78.0];
const DEFAULT_ZOOM = 5;

export default function MapView({ mapData }) {
  const { t } = useTranslation();
  const center = mapData?.center || DEFAULT_CENTER;
  const zoom = mapData?.zoom || DEFAULT_ZOOM;
  const markers = mapData?.markers || [];

  return (
    <div className="map-view">
      <div className="map-header">
        <h3>{t('map.title')}</h3>
        {markers.length > 0 && (
          <span className="marker-count">{t('map.markerCount', { count: markers.length })}</span>
        )}
      </div>

      <MapContainer
        center={DEFAULT_CENTER}
        zoom={DEFAULT_ZOOM}
        className="leaflet-container-custom"
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <MapUpdater center={center} zoom={zoom} />

        {markers.map((m, i) => (
          <Marker
            key={`${m.lat}-${m.lon}-${i}`}
            position={[m.lat, m.lon]}
            icon={createIcon(m.color)}
          >
            <Popup>
              <div className="marker-popup">
                <strong>{m.label}</strong>
                <pre>{m.popup}</pre>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      {/* Legend */}
      <div className="map-legend">
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#0ea5e9' }}></span>
          {t('map.legend.location')}
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#4caf50' }}></span>
          {t('map.legend.safePfz')}
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#ff9800' }}></span>
          {t('map.legend.caution')}
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#f44336' }}></span>
          {t('map.legend.unsafeAlert')}
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: '#00bcd4' }}></span>
          {t('map.legend.pfzGood')}
        </div>
      </div>
    </div>
  );
}

