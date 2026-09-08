# ORCA — Marine EcOsystem Reasoning with Collaborative Agents

**Smart India Hackathon 2026 · ISRO · Software Track · Space Technology Theme**

## Problem Statement

Marine stakeholders (fishermen, coastal authorities, researchers) rely on satellite Earth Observation data, weather forecasts, and oceanographic bulletins for daily decisions — but this data is scattered across multiple sources and requires manual cross-referencing.

**ORCA** is an Agentic AI-powered conversational platform that lets users ask natural-language questions like *"Is it safe to venture into the sea tomorrow morning?"* or *"Where is the nearest Potential Fishing Zone today?"* and get synthesized, explainable, evidence-backed answers — with supporting maps and reasoning trails — by coordinating a team of specialized AI agents.

## What You Can Ask

| Query Type | Example | What Happens |
|---|---|---|
| 🛡️ **Sea Safety** | *"Is it safe to go fishing near Chennai?"* | Evaluates wave height, wind, visibility, active alerts → risk score |
| 🐟 **Fishing Zones** | *"Where is the nearest PFZ near Mumbai?"* | Analyzes SST + chlorophyll → ranked Potential Fishing Zones |
| 🌀 **Weather Alerts** | *"Are there any cyclone alerts near Vizag?"* | Checks active cyclone, lightning, high-wave advisories |

## Architecture

```
User Query (natural language)
  │
  ▼
┌─────────────────────────────┐
│  Orchestrator Agent         │  ← Intent detection (Gemini / keyword fallback)
│  (Gemini function calling)  │     + geocoding (30 coastal cities + Nominatim)
└──────────┬──────────────────┘
           │ selects 1 of 3 tools
           ▼
┌──────────────────────────────────────────────────┐
│  Ocean/Weather Agent → Data Sources (mock/live)  │
│  Risk Assessment Agent (wave, wind, vis, alerts) │
│  PFZ Agent (SST, chlorophyll scoring)            │
└──────────┬───────────────────────────────────────┘
           ▼
┌──────────────────────────┐
│  Synthesis Agent         │  → answer_text (markdown)
│  (LLM + template)       │  → evidence   (structured data)
└──────────┬───────────────┘  → map_data   (Leaflet markers)
           ▼
┌─────────────────┐    ┌──────────┐    ┌────────────────┐
│  Chat Panel     │    │  Map     │    │  Evidence Panel │
│  (React)        │    │ (Leaflet)│    │  ("Why this     │
│                 │    │          │    │   answer?")     │
└─────────────────┘    └──────────┘    └────────────────┘
```

Every recommendation carries a traceable evidence trail: which agents ran, which datasets/timestamps were used, and the rule/threshold that produced the conclusion.

## Tech Stack

- **LLM Orchestration:** Google Gemini 2.0 Flash (native function calling + exponential-backoff retry)
- **Backend:** Python / FastAPI
- **Frontend:** React (Vite) + Leaflet maps + Markdown rendering
- **Data:** Mock datasets (Chennai, Vizag, Mumbai) with live API stubs (Open-Meteo)

## Getting Started

### Prerequisites
- Python 3.9+
- Node.js 18+
- (Optional) [Gemini API key](https://aistudio.google.com/apikey) — works without it using keyword fallback

### 1. Clone & configure

```bash
git clone <repo-url>
cd OCRA-SIH
cp .env.example .env
# Optional: add your Gemini API key in .env
```

### 2. Backend setup

```bash
cd backend
pip3 install -r requirements.txt
python3 -m uvicorn main:app --reload
# → Running at http://localhost:8000
# → API docs at http://localhost:8000/docs
```

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev
# → Running at http://localhost:5173
```

### 4. Open the app

Navigate to **http://localhost:5173** and try one of the sample queries!

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe — returns status, version, Gemini config |
| `POST` | `/query` | Accept `{"query": "..."}` → returns `{answer_text, evidence, map_data}` |

### Example

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Is it safe to venture into the sea near Chennai?"}'
```

## Project Structure

```
OCRA-SIH/
├── backend/
│   ├── agents/
│   │   ├── orchestrator.py      # Intent detection + handler dispatch
│   │   ├── ocean_weather.py     # Marine data retrieval
│   │   ├── risk_assessment.py   # Safety scoring (deterministic thresholds)
│   │   ├── pfz.py               # Fishing zone analysis (SST + chlorophyll)
│   │   └── synthesis.py         # LLM/template answer + map + evidence
│   ├── data_sources/
│   │   ├── interface.py         # MarineConditions dataclass + provider switch
│   │   ├── mock_provider.py     # Reads from mock_data/ (Haversine nearest-match)
│   │   └── live_provider.py     # Open-Meteo API stub
│   ├── utils/
│   │   └── geocoding.py         # 30 coastal cities + Nominatim fallback
│   ├── tests/                   # 50 unit + integration tests
│   ├── main.py                  # FastAPI app (POST /query, GET /health)
│   ├── config.py                # Centralized env config
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatPanel.jsx    # Chat UI with sample queries + markdown
│   │   │   ├── MapView.jsx      # Leaflet map with color-coded markers
│   │   │   └── EvidencePanel.jsx # Collapsible "why this answer" panel
│   │   ├── App.jsx              # 3-panel layout
│   │   └── main.jsx
│   └── package.json
├── mock_data/
│   ├── chennai.json             # Safe conditions, 2 PFZ zones
│   ├── visakhapatnam.json       # Cyclone DANA + high-wave alert
│   └── mumbai.json              # Lightning alert, 1 PFZ zone
├── .env.example
└── README.md
```

## Data Sources

- **Mock (default):** Realistic JSON profiles for 3 Indian coastal cities
- **Live (opt-in):** Set `USE_LIVE_DATA=true` in `.env`
  - [Open-Meteo Marine API](https://open-meteo.com/) — SST, wave height, wind
  - [INCOIS](https://incois.gov.in) — PFZ advisories, ocean state forecasts
  - [IMD](https://mausam.imd.gov.in) — weather forecasts, cyclone alerts

## Testing

```bash
cd backend
python3 -m pytest tests/ -v
# 50 tests: data sources (12) + agents (21) + orchestrator (17)
```

## Team

- Pavithran
- BalaYoghi V

## License

TBD
