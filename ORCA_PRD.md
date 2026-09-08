# Product Requirements Document (PRD)
## ORCA — Marine EcOsystem Reasoning with Collaborative Agents

**Version:** 1.0
**Status:** Draft
**Track:** Smart India Hackathon — ISRO, Software Track, Space Technology Theme
**Prepared for:** ORCA Team

---

## 1. Overview

ORCA is an Agentic AI-powered conversational platform that lets marine stakeholders — fishermen, coastal authorities, researchers, and maritime operators — ask natural-language questions about ocean and weather conditions and get synthesized, evidence-based, explainable answers. It fuses satellite Earth Observation data (SST, chlorophyll, etc.), weather forecasts, tide data, and marine advisories, and coordinates a team of specialized AI agents (planning, data retrieval, ocean analytics, risk assessment, geospatial reasoning, visualization) to answer complex, multi-source questions like "Is it safe to go fishing tomorrow near my location?" — with maps, charts, and cited reasoning, not just raw data dumps.

## 2. Problem Statement

Marine data (SST, chlorophyll concentration, weather, tides, cyclone/lightning alerts, PFZ advisories) is abundant but fragmented across ISRO and other agency sources. Stakeholders currently must manually cross-reference multiple portals/bulletins to make operational decisions (where to fish, whether it's safe to sail, which routes to avoid). There is no single conversational system that autonomously retrieves, correlates, and reasons over this heterogeneous data to produce a trustworthy, explainable recommendation.

## 3. Goals & Objectives

- Let a user ask a plain-language marine question and get a synthesized answer, not a link to a dataset.
- Auto-detect query language (with emphasis on Indian regional languages) and respond in kind.
- Support multi-turn, context-aware conversation (e.g., "what about the day after?" following a prior query).
- Autonomously plan, decompose, and route sub-tasks across specialized agents.
- Correlate multiple data sources (EO + weather + tide + advisories) rather than answering from a single dataset.
- Make every recommendation explainable — show the evidence/reasoning chain, not just a conclusion.
- Proactively surface safety-critical alerts (cyclone, lightning, high waves) and geofencing warnings (IMBL, MPAs, restricted waters).
- Present answers with supporting maps/charts, not text alone.

### Non-goals (for hackathon prototype)
- Not building new satellite sensors or raw EO data pipelines — will consume existing/public products (INCOIS, IMD, Bhuvan/ISRO open data, etc.).
- Not a full production-grade navigation/autopilot system — route "optimization" is advisory, not vessel control.
- Not attempting full coverage of all Indian languages in v1 — prototype targets a representative subset (e.g., Tamil, Hindi, English) with an architecture that generalizes.

## 4. Target Users / Personas

| Persona | Needs |
|---|---|
| **Fisherman** | Simple, local-language answers: where to fish, is it safe, alerts near my location |
| **Coastal disaster management authority** | Region-wide hazard summaries, cyclone/lightning alerts, evacuation-relevant conditions |
| **Marine researcher** | Correlated chlorophyll/SST trends, explanations for productivity changes |
| **Maritime operator (vessel routing)** | Safe-route suggestions factoring weather/sea-state, geofencing near IMBL/MPAs |

## 5. Key User Stories

1. As a fisherman, I want to ask "Where is the nearest Potential Fishing Zone today?" and get a map pin with distance and reasoning (chlorophyll + SST thresholds).
2. As a fisherman, I want to ask "Is it safe to venture into the sea tomorrow morning?" and get a yes/no with the specific hazards behind that answer (wave height, wind, alerts).
3. As a maritime operator, I want a safe route between two points that avoids hazardous sea-state and restricted zones, with alternatives if conditions change.
4. As a researcher, I want to ask "Why has fish productivity declined near [region]?" and get a correlated explanation across SST/chlorophyll trends over time.
5. As any user, I want to be proactively warned if I'm approaching an international maritime boundary or marine protected area.
6. As a non-English speaker, I want to ask my question in my language and get the answer back in the same language.
7. As a returning user, I want to refine a prior query ("what about further north?") without restating full context.

## 6. Scope

### In scope (hackathon prototype)
- Conversational chat interface (text; voice optional/stretch).
- Language detection + response generation in detected language (subset of Indian languages + English).
- Multi-agent orchestration: Planner/Orchestrator agent + specialized agents (see Section 8).
- Integration with a limited set of real, public marine/weather data sources.
- Map-based visualization of PFZ, hazards, and routes.
- Explainability panel showing which data sources/reasoning steps produced an answer.
- Basic geofencing alert logic (IMBL, sample MPA boundaries).
- Multi-turn conversation memory within a session.

### Out of scope (for now)
- Real-time vessel tracking/hardware integration.
- Full historical trend modeling / ML forecasting of fish stock.
- Production-grade authentication, multi-tenant scaling, offline/low-bandwidth mode (note as future work, since real fishermen often have poor connectivity).

## 7. System Architecture

### 7.1 High-level flow
```
User (text/voice, any language)
   → Language Detection & Translation Layer
   → Orchestrator/Planner Agent (intent parsing, task decomposition)
   → Specialized Agents (parallel/sequential as needed)
        - Marine Data Discovery Agent
        - Weather Intelligence Agent
        - Ocean Analytics Agent (SST, chlorophyll, PFZ logic)
        - Geospatial Reasoning Agent (routing, geofencing)
        - Risk Assessment Agent (safety scoring, alerts)
        - Visualization Agent (maps/charts)
        - Reporting/Synthesis Agent (final answer + explanation)
   → Response Translation Layer (back to user's language)
   → Conversational UI (text + map + chart + evidence trail)
```

### 7.2 Agent responsibilities

| Agent | Responsibility |
|---|---|
| **Orchestrator/Planner** | Parses intent, decomposes into sub-tasks, decides which agents to invoke and in what order, aggregates results |
| **Marine Data Discovery** | Locates and fetches relevant datasets (EO products, advisories) for the query's spatial-temporal scope |
| **Weather Intelligence** | Retrieves forecasts, cyclone/lightning alerts, wind/wave data |
| **Ocean Analytics** | Computes/interprets SST, chlorophyll concentration, applies PFZ identification logic |
| **Geospatial Reasoning** | Spatial queries, distance/route calculation, geofencing checks (IMBL, MPAs, restricted zones) |
| **Risk Assessment** | Combines hazard signals into a safety verdict/score with justification |
| **Visualization** | Generates map layers, charts, overlays for the response |
| **Reporting/Synthesis** | Composes final natural-language answer with citations to source agents/data, formats explanation trail |

### 7.3 Explainability requirement
Every synthesized answer must carry a traceable record of: which agents were invoked, which datasets/timestamps were used, and the rule/threshold or model output that produced the conclusion. This is shown to the user as an expandable "why this answer" section.

## 8. Functional Requirements

| ID | Requirement |
|---|---|
| FR-1 | System shall accept natural-language text queries and detect the query language |
| FR-2 | System shall respond in the same language as the query |
| FR-3 | System shall maintain conversational context across turns within a session |
| FR-4 | System shall decompose a complex query into sub-tasks and route to appropriate agents |
| FR-5 | System shall retrieve and integrate data from at least: SST source, chlorophyll source, weather/forecast source, tide source, and hazard advisory source |
| FR-6 | System shall identify Potential Fishing Zones based on SST/chlorophyll thresholds and location |
| FR-7 | System shall assess sea-venture safety using wave height, wind, and active alerts |
| FR-8 | System shall generate route suggestions considering weather/sea-state and flag geofenced areas |
| FR-9 | System shall proactively flag cyclone/lightning alerts and geofencing breaches relevant to the user's stated/implied location |
| FR-10 | System shall render map-based visualizations (PFZ location, hazard zones, routes) alongside text answers |
| FR-11 | System shall present an evidence/reasoning trail for every recommendation |
| FR-12 | System shall handle location input via place name, coordinates, or "my location" |

## 9. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 | Response latency target: under ~8–10s for a single-region query in the prototype (multi-agent calls in parallel where possible) |
| NFR-2 | Explainability: no answer delivered without a traceable source/reasoning reference |
| NFR-3 | Modularity: each agent independently swappable/testable (clean interface contracts) |
| NFR-4 | Data freshness: clearly timestamp all data shown, since EO/weather data updates on different cadences |
| NFR-5 | Graceful degradation: if a data source is unavailable, system states the gap rather than fabricating values |
| NFR-6 | Extensibility: architecture should allow adding new agents/data sources without redesigning the orchestrator |

## 10. Candidate Data Sources (public domain)

- **INCOIS** (Indian National Centre for Ocean Information Services) — PFZ advisories, ocean state forecasts, tsunami/high-wave warnings
- **IMD** (India Meteorological Department) — weather forecasts, cyclone, lightning alerts
- **ISRO Bhuvan / MOSDAC** — satellite EO products (SST, chlorophyll, ocean color)
- **Copernicus Marine Service** — supplementary SST/chlorophyll if Indian-source coverage is thin
- **OpenStreetMap / GIS boundary layers** — coastline, IMBL reference, MPA boundaries (sample set for prototype)

*(Note: exact API availability/access should be verified early — this is a key technical risk; see Section 12.)*

## 11. Suggested Tech Stack (prototype-appropriate)

- **Orchestration:** LLM-based agent framework (e.g., LangGraph / CrewAI / custom orchestrator over an LLM with tool-calling)
- **Backend:** Python (FastAPI) for agent services and data integration
- **Geospatial:** GeoPandas / Shapely for spatial reasoning, Leaflet/Mapbox for map rendering
- **Frontend:** React-based chat UI with embedded map/chart components
- **Data layer:** Scheduled fetch/cache of public datasets (avoid hitting rate limits live per query)
- **Language handling:** Language ID model + translation API/model for regional language support

## 12. Risks & Assumptions

| Risk/Assumption | Notes |
|---|---|
| Public data source access/rate limits unknown until tested | Validate INCOIS/IMD/MOSDAC access early — highest technical risk |
| Real-time cyclone/lightning alert feeds may not be freely API-accessible | May need to scrape/parse bulletins as fallback |
| Regional language coverage limited in prototype | Architecture should generalize; full language coverage is future work |
| "Safety" verdicts are advisory only | PRD assumes no liability claims; must be stated clearly in UI as advisory, not authoritative |
| Multi-agent latency could exceed target under sequential data fetches | Mitigate via parallel agent calls where sub-tasks are independent |

## 13. Success Metrics (for demo/judging)

- Correctly answers each of the 8 sample query types from the problem statement, end-to-end, with live/near-live data.
- Demonstrates at least 2 languages (e.g., English + one Indian regional language) with correct detection and response.
- Every demoed answer shows a visible reasoning/evidence trail.
- Multi-turn refinement demonstrated (follow-up query reusing context).
- Map/chart visualization renders correctly for at least PFZ and route-safety queries.

## 14. Future Scope (post-hackathon)

- Offline/low-bandwidth mode and SMS/USSD fallback for fishermen with poor connectivity.
- Full Indian regional language coverage.
- Historical trend modeling for productivity decline analysis (beyond current-state correlation).
- Push notifications for proactive alerts (not just query-response).
- Mobile app with GPS-based auto-location.

---

*This PRD scopes ORCA for a hackathon prototype: a working demonstration of agentic orchestration, multi-source correlation, and explainable marine recommendations — not a production system.*
