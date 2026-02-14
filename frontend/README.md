# Teletraan Frontend

Next.js 16 frontend for the Teletraan market intelligence application. Built with React 19, TypeScript, TanStack Query, shadcn/ui, and Recharts.

## Getting Started

Install dependencies:
```bash
npm install
```

Run the development server:
```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Build & Deploy

Production build (static export for desktop app):
```bash
npm run build
```

Lint code:
```bash
npm run lint
```

Run E2E tests:
```bash
npx playwright test
```

Run specific E2E test:
```bash
npx playwright test tests/integration.spec.ts
```

## Project Structure

```
frontend/
  app/                       Next.js App Router pages
    page.tsx                Analytics dashboard (home)
    runs/page.tsx           Past analysis runs with metrics
    insights/               Insights exploration
    portfolio/              Portfolio tracking
    research/               Follow-up research
    chat/                   Real-time chat interface
    reports/                Report listing & viewing
  components/               React components
    insights/               Insight-related components
    portfolio/              Portfolio components
    dashboard/              Dashboard charts & widgets
  lib/
    api.ts                  Typed API client (fetchApi, postApi)
    hooks/
      use-runs.ts          TanStack Query hooks for runs data
      use-insights.ts      Hooks for insights
      use-chat.ts          WebSocket chat hook
      use-portfolio.ts     Portfolio hooks
  types/                    TypeScript type definitions
  public/                   Static assets (icons, images)
```

## Key Patterns

- **API Integration**: `fetchApi()` and `postApi()` in `lib/api.ts` for typed HTTP requests
- **Server State**: TanStack Query (`@tanstack/react-query`) for data fetching with 1-min stale time, 10-min cache
- **WebSocket Chat**: `useChat` hook manages real-time connection with auto-reconnect
- **Path Alias**: `@/*` maps to project root (configured in `tsconfig.json`)
- **Components**: kebab-case filenames with `use-*` prefix for custom hooks
- **Client Components**: `'use client'` directive on interactive pages
- **Styling**: shadcn/ui (new-york style) + Tailwind CSS 4

## Pages

- **Home** (`app/page.tsx`) — Analytics dashboard with market overview
- **Runs** (`app/runs/page.tsx`) — Past analysis runs with paginated list, filtering, and aggregate stats (LLM metrics, cost, timing)
- **Insights** (`app/insights/`) — Explore deep insights with pattern recognition
- **Portfolio** (`app/portfolio/`) — Track holdings with live prices and insight correlation
- **Chat** (`app/chat/`) — Real-time conversational analysis with 10 market data tools
- **Reports** (`app/reports/`) — View published HTML reports
- **Research** (`app/research/`) — Follow-up research management

## Runs Dashboard (`app/runs/page.tsx`)

Displays past analysis runs with detailed LLM metrics:
- Paginated list with status and text filtering
- Per-run metrics: input/output tokens, cost, model, provider, timing
- Aggregate stats: total cost, token usage, success rates, average duration
- Phase-level breakdowns (macro scan, sector rotation, deep dive, etc.)

Powered by `useRuns()` and `useRunsStats()` hooks from `lib/hooks/use-runs.ts`.

## Environment Variables

**Frontend** (`frontend/.env.local` — auto-created by `start.sh`):
- `NEXT_PUBLIC_API_URL` — Backend API base URL (default: `http://localhost:8000`)
- `NEXT_PUBLIC_WS_URL` — WebSocket URL for chat (default: `ws://localhost:8000/api/v1/chat`)

## Learn More

- [Next.js Documentation](https://nextjs.org/docs)
- [React Documentation](https://react.dev)
- [TanStack Query Documentation](https://tanstack.com/query)
- [shadcn/ui Documentation](https://ui.shadcn.com)
