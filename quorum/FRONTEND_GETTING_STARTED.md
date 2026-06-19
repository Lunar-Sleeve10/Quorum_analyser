# Quorum Next.js frontend — start from scratch (Windows-first)

The zip ships the frontend SOURCE in `quorum/frontend-next/` (pages, components,
hooks, lib, store) but not `package.json`/`node_modules`. You scaffold a fresh
Next.js app once, then copy these files on top. ~5 steps.

Prerequisites: Node 18.18+ (`node -v`), and pnpm (`npm i -g pnpm`). The backend
must be running (Steps in GETTING_STARTED.md, Step 7) on http://localhost:8000.

## 1. Unzip and open a terminal

Unzip `quorum_v2_complete.zip`. In File Explorer open the `quorum` folder, click
the address bar, type `powershell`, Enter.

## 2. Scaffold a fresh Next.js app (creates package.json, config, etc.)

```
pnpm create next-app@latest quorum-ui --ts --tailwind --eslint --app --no-src-dir --import-alias "@/*"
```
Accept the defaults it offers (Turbopack is fine).

## 3. Overlay the provided source onto it

```
Copy-Item -Recurse -Force .\frontend-next\* .\quorum-ui\
cd quorum-ui
```
(macOS/Linux: `cp -r frontend-next/* quorum-ui/ && cd quorum-ui`.)

## 4. Install deps and generate the shadcn/ui components

```
pnpm add @tanstack/react-query zustand recharts jspdf
pnpm dlx shadcn@latest init -d
pnpm dlx shadcn@latest add button card input textarea badge table separator
```
If `init` asks about overwriting globals.css, say yes.

## 5. Point it at the backend and run

```
Copy-Item .env.local.example .env.local
pnpm dev
```
Open http://localhost:3000.

`.env.local` should contain (default is correct for local):
```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Use it

1. Backend running on :8000 (separate terminal). For real answers it needs an
   LLM configured (Ollama/Groq) and DB_PATH set — same as the console.
2. Dashboard is the landing page. Open Data Sources to confirm your DB is listed.
3. Investigations → pick the data source, ask a question (e.g. "top 10 customers
   by revenue"), click Ask.
4. Band Rooms → watch the live discussion; Insights → the result; Investigation
   Details → ask a follow-up (now reuses the original context).

## Production build check (recommended once)

```
pnpm build
```
If a type error appears, it will name the file — paste it and it's a quick fix.

## Troubleshooting

- Blank data / "—" everywhere: the backend isn't running, or
  `NEXT_PUBLIC_API_BASE_URL` is wrong. Confirm http://localhost:8000/healthz.
- CORS error in the browser console: the backend allows all origins by default
  (`FRONTEND_ORIGIN=*`); restart the backend if you changed it.
- A `@/components/ui/...` import fails: re-run the `shadcn add` line in Step 4.
- Charts not rendering: ensure `pnpm add recharts` ran (Step 4).
