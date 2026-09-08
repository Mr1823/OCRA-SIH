import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import axios from 'axios';
import './ChatPanel.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const SAMPLE_QUERIES = [
  '🛡️ Is it safe to venture into the sea near Chennai?',
  '🐟 Where is the nearest PFZ near Mumbai?',
  '🌀 Are there any cyclone alerts near Vizag?',
];

export default function ChatPanel({ onResponse }) {
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
      const res = await axios.post(`${API_URL}/query`, { query });
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
        text: `⚠️ **Error**: ${err.response?.data?.detail || err.message || 'Could not reach the ORCA backend. Is it running?'}`,
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

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <h2>🐋 ORCA</h2>
        <span className="chat-subtitle">Marine Intelligence Assistant</span>
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <p className="welcome-title">Welcome to ORCA!</p>
            <p className="welcome-desc">
              Ask me about sea safety, fishing zones, or weather alerts along
              the Indian coast.
            </p>
            <div className="sample-queries">
              {SAMPLE_QUERIES.map((q, i) => (
                <button
                  key={i}
                  className="sample-btn"
                  onClick={() => handleSampleClick(q)}
                >
                  {q}
                </button>
              ))}
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

      <form className="chat-input-bar" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about sea conditions, fishing zones, or alerts…"
          disabled={loading}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}

