# Quorum UI

Frontend for the Quorum governed analytics system. A Next.js 16 workspace that presents multi-agent investigation sessions, real-time agent activity, and governance audit trails.

## Prerequisites

- Node.js 20+
- pnpm 9+
- Quorum backend running at `http://localhost:8000` (see `../quorum/`)

## Getting started

```bash
pnpm install
pnpm dev          # http://localhost:3000
```

Production build:

```bash
pnpm build
pnpm start
```

## Environment variables

Create `.env.local` in this directory to override defaults:

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | FastAPI backend base URL |

## Entry flow

Visiting `http://localhost:3000` for the first time redirects to the **cover page** (`/cover`) — a Three.js animated agent network that checks backend health, lets you pick a data source, and optionally submit a question before entering the workspace.

When you click **Enter dashboard**, the cover sets a `quorum_entered` cookie and navigates to `/` (or directly to `/investigations/<id>` if an investigation was started from the cover). Subsequent visits skip the cover and land on the dashboard directly. Clear the cookie to see the cover again.

The redirect is handled by `proxy.ts` (Next.js 16 proxy). The cover is served via `app/cover/route.ts` which injects `NEXT_PUBLIC_API_BASE_URL` at request time — this makes the cover point at the correct backend in both local dev and production (Vercel + Render).

## Project structure

```
quorum-ui/
├── app/
│   ├── layout.tsx               # Root layout: sidebar + header shell
│   ├── page.tsx                 # Dashboard home (KPIs, recent, demo DBs)
│   ├── cover/route.ts           # Dynamic cover page handler (injects API_BASE)
│   ├── investigations/
│   │   ├── page.tsx             # Investigations list + question input
│   │   └── [id]/page.tsx        # Investigation detail (timeline, agents, verdict)
│   ├── data-sources/page.tsx    # Connect / upload databases
│   ├── insights/page.tsx        # Cross-investigation insights
│   ├── audit/page.tsx           # Full governance audit log
│   └── system/page.tsx          # Backend system status
│
├── components/
│   ├── workflow-timeline.tsx    # 8-stage execution pipeline visualisation
│   ├── agent-room.tsx           # Real-time agent card grid + SSE transcript
│   ├── cost-panel.tsx           # Query cost, risk badge, expandable SQL
│   ├── status-badge.tsx         # Semantic status pill with icon
│   ├── topology-badge.tsx       # Governed chain / Investigation board badge
│   ├── app-sidebar.tsx          # Left navigation
│   ├── app-header.tsx           # Top bar with quota pill
│   ├── motion/                  # Reusable animation wrappers (Motion)
│   └── ui/                      # shadcn/ui primitives (Button, Card, …)
│
├── hooks/use-api.ts             # React Query hooks (useInvestigation, useRoom, …)
├── lib/
│   ├── api.ts                   # Typed fetch wrapper + all API endpoints
│   ├── types.ts                 # Shared TypeScript types
│   └── utils.ts                 # cn() helper
├── store/session.ts             # Zustand: session token, saved items, data source
│
├── public/cover.html            # Standalone Three.js cover page (static source)
├── proxy.ts                     # Next.js 16 proxy: cover-page redirect on first visit
└── next.config.ts
```

## Pages

| Route | Description |
|---|---|
| `/` | Dashboard: KPI cards, active/recent investigations, demo databases, how-it-works |
| `/investigations` | List all investigations; submit a new question to start one |
| `/investigations/[id]` | Full detail: 8-stage pipeline, live agent cards, board verdict, governance panel, follow-up |
| `/data-sources` | Upload a SQLite file or connect an external database; manage sources |
| `/insights` | Aggregated findings across completed investigations |
| `/audit` | Governance event log with filters |
| `/system` | Backend health, LLM config, database stats |

## Key components

**`WorkflowTimeline`** — 8-stage lifecycle visualisation (Question → Planning → Governance → SQL Generation → SQL Validation → Data Review → Reporting → Completed). Current stage is derived from `InvestigationDetail` fields at render time. Hovering a stage shows a description panel rendered outside the scroll container to avoid clipping.

**`AgentRoom`** — consumes the SSE stream at `/rooms/{id}/stream`. Maintains a deduplicated, chronologically sorted message list with a reveal timer. Above the transcript it renders per-agent status cards (name, role, status, last decision, revision count) derived from visible messages. The transcript is collapsible.

**`CostPanel`** — displays query risk level, estimated cost, rows scanned, and the approved SQL in an expandable section (`"use client"` — uses `useState` for expand toggle).

## API layer

All backend calls go through `lib/api.ts`. The `req<T>()` helper:
- Reads the session token from Zustand and sends it as `X-Session-Token`
- Automatically stores any `session_token` returned in a response back into Zustand
- Throws using the `detail` field from FastAPI error responses

React Query hooks in `hooks/use-api.ts` wrap these calls with caching and background polling (running investigations poll every 3 s).

SSE streaming uses a raw `EventSource` inside `AgentRoom` — React Query is not used for the stream.

## Tech stack

| Package | Version | Role |
|---|---|---|
| Next.js | 16.2.9 | Framework (App Router, Turbopack) |
| React | 19 | UI |
| TypeScript | 5 | Types |
| Tailwind CSS | 4 | Styling (OKLch colour space) |
| Motion | 12 | Animations (`motion/react`) |
| TanStack Query | 5 | Server state / polling |
| Zustand | 5 | Client state (session token, saved items) |
| shadcn/ui | 4 | Component primitives |
| Lucide React | 1.20 | Icons |
| Recharts | 3 | Charts (insights page) |
| jsPDF | 4 | Report PDF export |
| Three.js | r128 (CDN) | Cover page 3D agent network |
