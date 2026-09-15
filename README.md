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
| 🌀 **Weather Alerts** | *"Are there any cyclone alerts near Vizag?"* | Checks active cyclone, lightning, high-wave, weather and port warnings |

Questions can be about **today or a specific day up to a week ahead** (*"…tomorrow?"*, *"…on 2026-09-18?"*), and can be asked in **English or Tamil** (UI toggle; Tamil queries such as *"சென்னை அருகில் கடலுக்குச் செல்வது பாதுகாப்பானதா?"* are understood too).

## Architecture

```
User Query (natural language)
  │
  ▼
┌─────────────────────────────┐
│  Orchestrator Agent         │  ← Intent detection (Groq → keyword fallback)
│  (LLM tool calling)         │     + geocoding (coastal cities, 13 TN districts, Nominatim)
└──────────┬──────────────────┘
           │ selects 1 of 3 tools
           ▼
┌──────────────────────────────────────────────────┐
│  Ocean/Weather Agent → Data Sources (mock/live)  │
│  Risk Assessment Agent (wave, wind, vis, alerts) │
│  PFZ Agent (SST, chlorophyll) + safety check     │
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

### How answers stay honest

Safety verdicts are deterministic rules (`backend/agents/risk_assessment.py`); an LLM only words them. On top of that:

- **Alerts are default-deny.** Cyclone and tsunami alerts → unsafe; high-wave, lightning, weather and port warnings → caution; any unrecognised or untyped alert → caution. An alert is never silently ignored.
- **Placeholder alert data is always labelled.** Without a working IMD feed, alerts come from built-in sample bulletins, and every answer says so — including when that sample data has *no* alerts, which is not a confirmed all-clear.
- **Missing readings are reported, never invented.** A null wave height, wind or visibility from the API is shown as unavailable and forces at least "caution".
- **Dates are respected.** "Tomorrow" uses Open-Meteo's forecast for that day (its roughest hour). If no forecast for the requested day is available (demo data, past or too-distant dates), the answer says it only checked current conditions.
- **Fishing-zone answers include the safety check** and lead with a warning whenever conditions aren't clean.
- These notes are added after the answer is generated, so an LLM-written answer can't drop them.

## Tech Stack

- **LLM orchestration:** Groq (`openai/gpt-oss-120b`) → keyword/template fallback, via async clients with bounded retries (`backend/utils/llm.py`)
- **Backend:** Python / FastAPI
- **Frontend:** React (Vite) + Leaflet maps + Markdown rendering, English/Tamil UI (i18next)
- **Data:** Open-Meteo (marine + weather, current and forecast), IMD (alerts), Copernicus Marine (chlorophyll-a); mock datasets for offline demos

## Getting Started

### Prerequisites
- Python 3.9+
- Node.js 18+
- (Optional) [Groq API key](https://console.groq.com) — everything works without it via keyword detection and template answers
- (Optional) IMD API key and Copernicus Marine account for live alerts and chlorophyll

### 1. Clone & configure

```bash
git clone <repo-url>
cd OCRA-SIH
cp .env.example .env
# Optional: add API keys and set USE_LIVE_DATA=true in .env
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
| `GET` | `/health` | Liveness probe — returns status, version, LLM config |
| `POST` | `/query` | Accept `{"query": "...", "language": "en" \| "ta"}` → returns `{answer_text, evidence, map_data}` |

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
│   │   ├── orchestrator.py      # Intent detection (Groq → keywords) + handler dispatch
│   │   ├── ocean_weather.py     # Marine data retrieval
│   │   ├── risk_assessment.py   # Safety verdict (deterministic thresholds, default-deny alerts)
│   │   ├── pfz.py               # Fishing zone analysis (SST + chlorophyll)
│   │   └── synthesis.py         # LLM/template answer (en/ta) + honesty notes + map + evidence
│   ├── data_sources/
│   │   ├── interface.py         # MarineConditions dataclass + provider switch
│   │   ├── mock_provider.py     # Reads from mock_data/ (Haversine nearest-match)
│   │   ├── live_provider.py     # Open-Meteo current conditions + day forecasts, IMD, Copernicus
│   │   ├── imd_provider.py      # IMD cyclone track + coastal bulletins (sample data without a key)
│   │   └── copernicus_provider.py # Copernicus chlorophyll-a (climatology fallback)
│   ├── utils/
│   │   ├── geocoding.py         # Coastal cities + 13 Tamil Nadu districts + Nominatim fallback
│   │   ├── dates.py             # "today" / "tomorrow" / ISO / Tamil date phrases → IST dates
│   │   └── llm.py               # Retry budget, retry-after handling, provider cooldowns
│   ├── tests/                   # 176 unit + integration tests
│   ├── main.py                  # FastAPI app (POST /query, GET /health)
│   ├── config.py                # Centralized env config
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/               # Landing page + chat app
│   │   ├── components/
│   │   │   ├── ChatPanel.jsx    # Chat UI, sample queries, TN district picker
│   │   │   ├── MapView.jsx      # Leaflet map with color-coded markers
│   │   │   ├── EvidencePanel.jsx # Collapsible "why this answer" panel
│   │   │   └── LanguageToggle.jsx # English / Tamil
│   │   ├── locales/             # en.json, ta.json
│   │   ├── App.jsx              # Routes: / (landing), /app (chat)
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

- **Mock (default):** Realistic JSON profiles for 3 Indian coastal cities (other locations borrow the nearest profile, and the answer says so)
- **Live (opt-in):** Set `USE_LIVE_DATA=true` in `.env`
  - [Open-Meteo](https://open-meteo.com/) Marine + Forecast APIs — wave height/period, SST, wind, visibility, weather; current conditions or the forecast for a requested day (up to 7 days ahead)
  - [IMD](https://mausam.imd.gov.in) API — cyclone track and coastal bulletins (needs `IMD_API_KEY`; otherwise built-in sample bulletins, clearly labelled)
  - [Copernicus Marine Service](https://marine.copernicus.eu) — satellite chlorophyll-a for fishing zones (needs `CMEMS_USERNAME`/`CMEMS_PASSWORD`; otherwise a labelled regional climatology). Live fishing-zone sampling is off unless `ENABLE_LIVE_PFZ_GRID=true`.
- **Not yet integrated:** INCOIS PFZ advisories, tide data in live mode

## LLM Reliability

Groq's free tier limits tokens per minute (8,000/min for `openai/gpt-oss-120b` on the key tested; a query uses ~1,200), so bursts of questions get rate-limited. The call policy in `backend/utils/llm.py` keeps that from stalling the app:

- Async SDK clients with an 8 s timeout (`LLM_REQUEST_TIMEOUT_S`) and no hidden SDK retries
- Retries honour the server's `retry-after`, never happen after the final attempt, and never wait more than `LLM_RETRY_WAIT_BUDGET_S` (3 s) in total before falling back
- If Groq can't answer at all (e.g. an invalid key), it's skipped for `LLM_PROVIDER_COOLDOWN_S`
- The keyword/template fallback always answers

## Testing

```bash
cd backend
python3 -m pytest tests/ -v
# 176 tests
```

The suite is hermetic: `tests/conftest.py` blanks API keys and forces mock data before `config.py` loads, so a local `.env` with real keys or `USE_LIVE_DATA=true` can't make tests call real services.

## Team

- Pavithran
- BalaYoghi V

## License

TBD
