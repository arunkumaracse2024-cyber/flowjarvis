# FlowJarvis ⚡
### SMB Operations Co-Pilot — FlowZint AI Hackathon 2026

FlowJarvis is a conversational decision engine that helps operations managers make high-stakes business decisions by combining live internal team data with real-time external market intelligence.

## Quick Start

**Prerequisites:** Python 3.10+, a browser (Chrome recommended)

**Step 1 — Start the backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Confirm startup output shows ✓ for both Supabase and Gemini.

**Step 2 — Open the frontend:**
Open `frontend/index.html` in Chrome. No server needed — it's a single HTML file.

**Step 3 — Ask a question:**
Type any business question. FlowJarvis will simultaneously audit your internal team and scan the market.

## Best Demo Questions

1. "Should we take on a new mobile app project for a client starting next month?"
2. "Which teams are at risk of burnout right now?"
3. "Should we hire a contract backend engineer for the ERP Migration?"

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18 + Tailwind CSS (CDN, no build step) |
| Backend | Python FastAPI |
| AI Orchestration | Google Gemini 1.5 Flash (function calling) |
| Internal Audit Tool | Supabase PostgreSQL (live queries) |
| Market Research Tool | Gemini Google Search Grounding |
| Output Format | Structured JSON → Visual UI Cards |

## Architecture

User question → Gemini orchestrator → calls both tools simultaneously →
Internal Audit (Supabase: employees, projects, sprints) +
Market Research (Gemini Search: live web data) →
Gemini synthesizes → Structured JSON → 4 UI cards rendered

## Hackathon Category
Open Innovation — FlowZint AI Hackathon 2026
