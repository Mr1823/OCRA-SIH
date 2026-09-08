# ORCA — Marine EcOsystem Reasoning with Collaborative Agents

Smart India Hackathon 2026 · ISRO · Software Track · Space Technology Theme

## Problem Statement

Marine stakeholders (fishermen, coastal authorities, researchers, maritime operators) rely on satellite Earth Observation data, weather forecasts, and oceanographic bulletins for daily decisions — but this data is scattered across multiple sources and requires manual cross-referencing.

**ORCA** is an Agentic AI-powered conversational platform that lets users ask natural-language questions like *"Is it safe to venture into the sea tomorrow morning?"* or *"Where is the nearest Potential Fishing Zone today?"* and get synthesized, explainable, evidence-backed answers — with supporting maps and reasoning trails — by coordinating a team of specialized AI agents over satellite EO, weather, tide, and marine advisory data.

## Architecture

A Planner/Orchestrator agent decomposes each query and routes it to specialized agents, then a Reporting agent synthesizes the final answer:

```
User (any language)
  → Language Detection & Translation Layer
  → Orchestrator / Planner Agent
      → Marine Data Discovery Agent
      → Weather Intelligence Agent
      → Ocean Analytics Agent (SST, chlorophyll, PFZ logic)
      → Geospatial Reasoning Agent (routing, geofencing)
      → Risk Assessment Agent (safety scoring, alerts)
      → Visualization Agent (maps/charts)
      → Reporting/Synthesis Agent (final answer + evidence trail)
  → Response Translation Layer
  → Conversational UI (text + map + chart + "why this answer" panel)
```

Every recommendation carries a traceable evidence trail: which agents ran, which datasets/timestamps were used, and the rule/threshold that produced the conclusion. Full detail in [`docs/PRD.md`](docs/PRD.md) — see [Data Sources](#data-sources) below for what each agent pulls from.

## Tech Stack

- **Orchestration:** LLM-based agent framework (LangGraph / CrewAI-style, tool-calling)
- **Backend:** Python (FastAPI)
- **Geospatial:** GeoPandas / Shapely, Leaflet/Mapbox for map rendering
- **Frontend:** React (chat UI + embedded map/chart components)
- **Language handling:** Language ID model + translation for regional language support

## Data Sources

- [INCOIS](https://incois.gov.in) — PFZ advisories, ocean state forecasts, high-wave warnings
- [IMD](https://mausam.imd.gov.in) — weather forecasts, cyclone, lightning alerts
- ISRO Bhuvan / MOSDAC — satellite EO products (SST, chlorophyll, ocean color)
- Copernicus Marine Service — supplementary SST/chlorophyll data
- OpenStreetMap / GIS layers — coastline, IMBL reference, MPA boundaries

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- API keys/access for data sources above (see `.env.example` once added)

### Backend setup
```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill in API keys
uvicorn main:app --reload
```

### Frontend setup
```bash
cd frontend
npm install
npm run dev
```

## Project Structure
```
orca-sih/
├── backend/
│   ├── agents/          # Planner, Marine Data, Weather, Ocean Analytics,
│   │                     # Geospatial, Risk Assessment, Visualization, Reporting
│   ├── services/         # data source integrations
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   └── package.json
├── docs/
│   └── PRD.md
└── README.md
```

## Team

- Pavithran
- BalaYoghi V

## License

TBD
