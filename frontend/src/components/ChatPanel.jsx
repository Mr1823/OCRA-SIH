import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import axios from 'axios';
import './ChatPanel.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const SAMPLE_QUERY_KEYS = ['safety', 'pfz', 'alerts'];

// All 13 coastal districts of Tamil Nadu, matching
// backend/utils/geocoding.py's get_all_tn_coastal_points() — a
// fisherman can pick a district by name instead of needing to know
// the exact coastal town ORCA resolves it to. Keys map into the
// districts.*/towns.* translation namespaces so labels (and the
// values ORCA actually receives) switch with the UI language.
const TN_DISTRICT_KEYS = [
  'thiruvallur', 'chennai', 'chengalpattu', 'villupuram', 'cuddalore',
  'nagapattinam', 'thiruvarur', 'thanjavur', 'pudukkottai', 'ramanathapuram',
  'thoothukudi', 'tirunelveli', 'kanyakumari',
];

const TN_TOWN_KEY_BY_DISTRICT = {
  thiruvallur: 'pazhaverkadu',
  chennai: 'chennai',
  chengalpattu: 'mamallapuram',
  villupuram: 'marakkanam',
  cuddalore: 'cuddalore',
  nagapattinam: 'nagapattinam',
  thiruvarur: 'vedaranyam',
  thanjavur: 'pointCalimere',
  pudukkottai: 'kottaipattinam',
  ramanathapuram: 'rameshwaram',
  thoothukudi: 'thoothukudi',
  tirunelveli: 'idinthakarai',
  kanyakumari: 'kanyakumari',
};

export default function ChatPanel({ onResponse }) {
  const { t, i18n } = useTranslation();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(scrollToBottom, [messages]);

  const sendQuery = async (query) => {
    if (!query.trim()) return;

    const userMsg = { role: 'user', text: query };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const res = await axios.post(`${API_URL}/query`, {
        query,
        language: i18n.resolvedLanguage || i18n.language,
      });
      const data = res.data;

      const assistantMsg = {
        role: 'assistant',
        text: data.answer_text,
        evidence: data.evidence,
        mapData: data.map_data,
      };

      setMessages((prev) => [...prev, assistantMsg]);
      onResponse?.(data);
    } catch (err) {
      const errorMsg = {
        role: 'assistant',
        text: `${t('chat.errorPrefix')}: ${err.response?.data?.detail || err.message || t('chat.errorFallback')}`,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    sendQuery(input);
  };

  const handleSampleClick = (q) => {
    // Strip the emoji prefix for cleaner queries
    const clean = q.replace(/^[^\w]*/, '').trim();
    sendQuery(clean);
  };

  const handleDistrictSelect = (e) => {
    const town = e.target.value;
    if (!town) return;
    const query =
      (i18n.resolvedLanguage || i18n.language) === 'ta'
        ? `இன்று ${town} அருகில் கடலுக்குச் செல்வது பாதுகாப்பானதா?`
        : `Is it safe to venture into the sea near ${town} today?`;
    sendQuery(query);
    e.target.value = ''; // reset so the same district can be re-selected later
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <h2>🐋 {t('chat.title')}</h2>
        <span className="chat-subtitle">{t('chat.subtitle')}</span>
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <p className="welcome-title">{t('chat.welcomeTitle')}</p>
            <p className="welcome-desc">{t('chat.welcomeDesc')}</p>
            <div className="sample-queries">
              {SAMPLE_QUERY_KEYS.map((key) => {
                const q = t(`chat.sampleQueries.${key}`);
                return (
                  <button key={key} className="sample-btn" onClick={() => handleSampleClick(q)}>
                    {q}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`chat-bubble ${msg.role}`}>
            {msg.role === 'assistant' ? (
              <ReactMarkdown>{msg.text}</ReactMarkdown>
            ) : (
              <p>{msg.text}</p>
            )}
          </div>
        ))}

        {loading && (
          <div className="chat-bubble assistant loading-bubble">
            <div className="typing-indicator">
              <span></span><span></span><span></span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="tn-district-picker">
        <select
          className="tn-district-select"
          defaultValue=""
          onChange={handleDistrictSelect}
          disabled={loading}
          aria-label="Quick-select a Tamil Nadu coastal district"
        >
          <option value="" disabled>
            {t('chat.districtPickerPlaceholder')}
          </option>
          {TN_DISTRICT_KEYS.map((districtKey) => {
            const town = t(`towns.${TN_TOWN_KEY_BY_DISTRICT[districtKey]}`);
            const district = t(`districts.${districtKey}`);
            return (
              <option key={districtKey} value={town}>
                {district} — {town}
              </option>
            );
          })}
        </select>
      </div>

      <form className="chat-input-bar" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t('chat.inputPlaceholder')}
          disabled={loading}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          {t('chat.send')}
        </button>
      </form>
    </div>
  );
}
