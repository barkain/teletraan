# Frontend Architecture Documentation

Comprehensive reference for the **Teletraan** frontend -- an AI-powered market intelligence dashboard built with Next.js 16, React 19, and TypeScript.

---

## Overview

Teletraan is a real-time market analysis application that combines autonomous AI-driven market scanning with interactive research tools. The frontend provides:

- A dashboard with autonomous analysis launcher and insight summaries
- Real-time WebSocket chat for conversational market research
- Deep insight cards with confidence scores, evidence, and trading parameters
- Sector heatmaps, treemaps, and price charts
- Background analysis with polling, progress bars, and localStorage persistence
- Dark mode support with system preference detection

---

## Tech Stack

| Category | Library | Version | Purpose |
|----------|---------|---------|---------|
| **Framework** | Next.js | 16.1.6 | App Router, SSR, code splitting |
| **UI Library** | React | 19.2.3 | Component rendering |
| **Language** | TypeScript | ^5 | Static typing |
| **State** | TanStack React Query | ^5.90.20 | Server state, caching, mutations |
| **Forms** | React Hook Form | ^7.71.1 | Form state management |
| **Validation** | Zod | ^4.3.6 | Schema validation |
| **Form Resolvers** | @hookform/resolvers | ^5.2.2 | Zod integration for forms |
| **Styling** | Tailwind CSS | ^4 | Utility-first CSS |
| **CSS Processing** | @tailwindcss/postcss | ^4 | PostCSS plugin for Tailwind |
| **Animation** | tw-animate-css | ^1.4.0 | Tailwind animation utilities |
| **Component Lib** | shadcn/ui (Radix) | Multiple | Accessible UI primitives |
| **Class Merging** | tailwind-merge | ^3.4.0 | Intelligent class conflict resolution |
| **Class Utils** | clsx | ^2.1.1 | Conditional class composition |
| **Variants** | class-variance-authority | ^0.7.1 | Component variant management |
| **Icons** | lucide-react | ^0.563.0 | Icon set |
| **Charts** | Recharts | ^3.7.0 | Data visualization |
| **Dates** | date-fns | ^4.1.0 | Date formatting |
| **Toasts** | Sonner | ^2.0.7 | Toast notifications |
| **Dark Mode** | next-themes | ^0.4.6 | Theme switching (system/light/dark) |
| **Command Menu** | cmdk | ^1.1.1 | Command palette |
| **Testing** | Playwright | ^1.58.0 | End-to-end browser testing |
| **Linting** | ESLint + eslint-config-next | ^9 / 16.1.6 | Code quality |

---

## Directory Structure

```
frontend/
  app/                          # Next.js App Router pages
    layout.tsx                  # Root layout (Header, Sidebar, Providers)
    page.tsx                    # Home / Insight Hub dashboard
    globals.css                 # Global styles and Tailwind imports
    chat/
      page.tsx                  # WebSocket chat interface
    conversations/
      page.tsx                  # Conversation listing across insights
    insights/
      page.tsx                  # Deep insights listing with filters
      [id]/
        page.tsx                # Single insight detail view
    stocks/
      page.tsx                  # Stock market data listing
    sectors/
      page.tsx                  # Sector performance visualization
    patterns/
      page.tsx                  # Knowledge pattern library
    signals/
      page.tsx                  # Statistical signals dashboard
    track-record/
      page.tsx                  # Outcome tracking and success metrics
    settings/
      page.tsx                  # User settings and preferences
  components/
    layout/
      header.tsx                # Sticky top navigation with badges
      sidebar.tsx               # Collapsible sidebar with primary/secondary nav
    chat/
      chat-container.tsx        # Chat wrapper with scroll area
      chat-input.tsx            # Message input with send button
      message-bubble.tsx        # Individual message rendering
      tool-call-display.tsx     # MCP tool call visualization
      suggested-prompts.tsx     # Pre-built prompt suggestions
    insights/
      deep-insight-card.tsx     # Card with action, confidence, evidence
      insight-card.tsx          # Legacy insight card
      insight-detail.tsx        # Full insight detail layout
      insight-detail-view.tsx   # Detailed view with tabs
      insight-filters.tsx       # Filter controls for insight listing
      insight-conversation-panel.tsx  # Chat panel within insight detail
      analysis-summary-banner.tsx     # Post-analysis summary display
      gradient-progress-bar.tsx       # Animated progress indicator
      annotation-form.tsx       # Insight annotation creation
      annotation-list.tsx       # Annotation listing
      discovery-context-card.tsx      # Macro context display
      statistical-signals-card.tsx    # Statistical feature signals
      pattern-library-panel.tsx       # Pattern matching panel
      outcome-badge.tsx         # Win/loss/pending outcome indicator
      track-record-dashboard.tsx      # Track record overview
    dashboard/
      market-overview.tsx       # Market indices and overview
      sector-overview.tsx       # Sector performance summary
      stats-cards.tsx           # Quick stat cards
      insights-summary.tsx      # Recent insights summary
    stocks/
      stock-table.tsx           # Tabular stock listing
      stock-header.tsx          # Stock detail page header
    charts/
      sector-heatmap.tsx        # Color-coded sector performance grid
      sector-treemap.tsx        # Proportional sector visualization
    export/
      export-button.tsx         # Export trigger button
      export-dialog.tsx         # Export format selection dialog
    ui/                         # shadcn/ui primitives (25+ components)
      alert-dialog.tsx          avatar.tsx
      badge.tsx                 button.tsx
      card.tsx                  checkbox.tsx
      collapsible.tsx           command.tsx
      dialog.tsx                dropdown-menu.tsx
      input.tsx                 label.tsx
      progress.tsx              scroll-area.tsx
      select.tsx                separator.tsx
      sheet.tsx                 skeleton.tsx
      sonner.tsx                table.tsx
      tabs.tsx                  textarea.tsx
      tooltip.tsx
    theme-provider.tsx          # next-themes ThemeProvider wrapper
    theme-toggle.tsx            # Light/dark/system theme switcher
    refresh-data-button.tsx     # ETL refresh trigger
    refresh-progress-dialog.tsx # Refresh progress modal
  lib/
    api.ts                      # API client (fetchApi, postApi, putApi, deleteApi)
    providers.tsx               # QueryClientProvider + Toaster
    utils.ts                    # cn() class merge utility
    hooks/                      # 13 custom React hooks
      use-analysis-task.ts      # Autonomous analysis lifecycle
      use-chat.ts               # General WebSocket chat
      use-deep-insights.ts      # Deep insight queries
      use-insight-conversation.ts # Conversation CRUD + WebSocket chat
      use-insights.ts           # Legacy insights with annotations
      use-market-data.ts        # Market overview aggregation
      use-refresh-data.ts       # ETL data refresh mutation
      use-search.ts             # Global/stock/insight search with debounce
      use-sectors.ts            # Sector performance + rotation detection
      use-statistical-features.ts # Statistical features + signals
      use-stock.ts              # Stock detail + price history
      use-track-record.ts       # Outcome tracking queries
      use-watchlist.ts          # Watchlist CRUD
    types/                      # Extended TypeScript interfaces
      index.ts                  # Re-exports
      knowledge.ts              # Pattern and theme types
      statistical-features.ts   # Signal and feature types
      track-record.ts           # Outcome and stats types
  types/
    index.ts                    # Core domain types (Stock, Insight, DeepInsight, etc.)
    chat.ts                     # Chat message and state types
  tests/                        # Playwright E2E tests
    integration.spec.ts         # Core integration tests
    api-mocks.spec.ts           # API mock tests
    debug-app.spec.ts           # App debugging tests
    debug-insights.spec.ts      # Insight debugging tests
    statistical-signals.spec.ts # Signal feature tests
    outcome-badge.spec.ts       # Outcome badge tests
    pattern-library.spec.ts     # Pattern library tests
    track-record.spec.ts        # Track record tests
  public/                       # Static assets (images, favicon)
  playwright.config.ts          # Playwright test configuration
  package.json                  # Dependencies and scripts
  tsconfig.json                 # TypeScript configuration
  next.config.ts                # Next.js configuration
```

---

## Pages and Routing

All pages use the Next.js App Router. Interactive pages include `'use client'` at the top.

| Route | File | Description |
|-------|------|-------------|
| `/` | `app/page.tsx` | Insight Hub dashboard with analysis launcher, stats cards, filter tabs, insight grid, and recent conversations |
| `/chat` | `app/chat/page.tsx` | General-purpose WebSocket chat with the market AI assistant |
| `/insights` | `app/insights/page.tsx` | Paginated deep insight listing with action/type/symbol filters |
| `/insights/[id]` | `app/insights/[id]/page.tsx` | Single insight detail with evidence, trading parameters, conversation panel, and pattern matching |
| `/conversations` | `app/conversations/page.tsx` | Cross-insight conversation listing with status filters |
| `/stocks` | `app/stocks/page.tsx` | Market data table with sector filtering |
| `/sectors` | `app/sectors/page.tsx` | Sector heatmap and treemap visualizations |
| `/patterns` | `app/patterns/page.tsx` | Knowledge pattern library from historical analysis |
| `/signals` | `app/signals/page.tsx` | Active statistical signals across the watchlist |
| `/track-record` | `app/track-record/page.tsx` | Outcome tracking dashboard with success rate metrics |
| `/settings` | `app/settings/page.tsx` | User preferences, watchlist configuration, API keys |

### Root Layout (`app/layout.tsx`)

The root layout wraps all pages with:

1. **ThemeProvider** (next-themes) -- class-based dark mode, defaults to system preference
2. **Providers** (TanStack Query) -- QueryClientProvider with global cache config + Sonner Toaster
3. **Header** -- Sticky top navigation bar
4. **Sidebar** -- Left sidebar (hidden on mobile via `hidden md:flex`)
5. **Main content area** -- `flex-1 p-6`

Fonts: Geist Sans and Geist Mono loaded via `next/font/google`.

---

## Component Architecture

### Layout Components

**Header** (`components/layout/header.tsx`)
- Sticky top bar with backdrop blur (`bg-background/95 backdrop-blur`)
- Logo with TrendingUp icon linked to home
- Desktop navigation: Primary items inline, secondary items in a Data dropdown
- Mobile navigation: Sheet (slide-out drawer) with full nav hierarchy
- Badge counts: Shows actionable insight count on "Insights" and watch count on "Research"
- Right side: ThemeToggle + user avatar dropdown menu
- Active link detection via `usePathname()` with prefix matching

**Sidebar** (`components/layout/sidebar.tsx`)
- Fixed-width left sidebar (w-64), hidden below `md` breakpoint
- Primary nav section ("Insights"): Home, Insights, Patterns, Track Record, Conversations, Research
- Secondary nav section ("Data"): Collapsible via Radix Collapsible, contains Market Data and Signals
- Bottom section: "Run Analysis" CTA button and Settings link
- Dynamic badge counts from `useDeepInsights` query

### Chat Components

**ChatContainer** -- Scroll area wrapper for message list
**ChatInput** -- Text input with send button, handles Enter key submission
**MessageBubble** -- Renders user/assistant messages with different styling
**ToolCallDisplay** -- Shows MCP tool invocations with name, args, and result status (pending/complete)
**SuggestedPrompts** -- Pre-built prompt cards for common market questions

### Insight Components

**DeepInsightCard** -- Primary card component showing:
- Action badge (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL, WATCH) with color coding
- Insight type badge (opportunity, risk, rotation, macro, divergence, correlation)
- Confidence score (0-100%)
- Primary symbol with click handler
- Thesis summary (truncated)
- Time horizon, entry zone, target price
- Click handler for navigation to detail page

**InsightDetailView** -- Full detail page with tabs for:
- Thesis and evidence from multiple analysts
- Trading parameters (entry, target, stop loss)
- Risk factors and invalidation triggers
- Historical precedent
- Discovery context (macro regime, sectors, opportunity type)
- Conversation panel for interactive research
- Statistical signals card
- Pattern matching panel

**AnalysisSummaryBanner** -- Post-completion banner showing market regime, top sectors, discovery summary, and elapsed time

**GradientProgressBar** -- Animated progress bar with phase name and details overlay, color gradient from primary to green

### Dashboard Components

**MarketOverview** -- Displays market indices (SPY, QQQ, DIA) with price, change, and percent change
**StatsCards** -- Grid of stat cards showing total insights, buy/sell/hold/watch signal counts
**SectorOverview** -- Sector performance summary cards
**InsightsSummary** -- Recent insights digest

### Chart Components

**SectorHeatmap** -- Color-coded grid of 11 S&P 500 sectors, performance mapped from red (-5%) through white (0%) to green (+5%)
**SectorTreemap** -- Proportional area visualization by market cap or volume

---

## State Management

### TanStack Query Configuration

Global defaults set in `lib/providers.tsx`:

```typescript
new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,        // 1 minute -- data is fresh for 1 min
      gcTime: 10 * 60 * 1000,      // 10 minutes -- keep in cache for stale-while-revalidate
      refetchOnWindowFocus: false,  // No refetch on tab focus
      refetchOnMount: true,         // Refetch stale data on mount
      retry: 1,                     // Only retry once
    },
  },
})
```

### Query Key Convention

All hooks use hierarchical query key factories for selective cache invalidation:

```typescript
// Deep insights keys
export const deepInsightKeys = {
  all: ['deep-insights'] as const,
  lists: () => [...deepInsightKeys.all, 'list'] as const,
  list: (params?: DeepInsightParams) => [...deepInsightKeys.lists(), params] as const,
  details: () => [...deepInsightKeys.all, 'detail'] as const,
  detail: (id: number) => [...deepInsightKeys.details(), id] as const,
  recent: (limit: number) => [...deepInsightKeys.all, 'recent', limit] as const,
};

// Insight keys
export const insightKeys = {
  all: ['insights'] as const,
  lists: () => [...insightKeys.all, 'list'] as const,
  list: (filters: InsightFilters) => [...insightKeys.lists(), filters] as const,
  details: () => [...insightKeys.all, 'detail'] as const,
  detail: (id: string) => [...insightKeys.details(), id] as const,
};

// Annotation keys
export const annotationKeys = {
  all: (insightId: string | number) => ['insight-annotations', String(insightId)] as const,
};
```

### Custom Hook Stale Times

Different hooks override the global staleTime based on data freshness requirements:

| Hook | staleTime | gcTime | Notes |
|------|-----------|--------|-------|
| `useDeepInsights` | 60s | 10min | Standard insight listing |
| `useRecentDeepInsights` | 30s | 10min | Dashboard, refreshes more often |
| `useInsights` | 60s | default | Legacy insights |
| `useInsightAnnotations` | 30s | default | Frequently updated |
| `useStock` | 30s | default | With exponential backoff retry |
| `useStockPriceHistory` | 60s | default | Historical data, less volatile |
| `useSectors` | 30s | default | Auto-refetch every 60s |
| `useMarketOverview` | 30s | default | Auto-refetch every 60s |
| `useTrackRecord` | 5min | default | Infrequently changing stats |
| `useStatisticalFeatures` | 2.5min | default | Auto-refetch every 5min |
| `useActiveSignals` | 30s | default | Auto-refetch every 60s |
| `useInsightConversation` | 10s | default | Active chat sessions |

---

## Custom Hooks Reference

### `useAnalysisTask` (use-analysis-task.ts, 387 lines)

Manages the full lifecycle of autonomous market analysis:

**State:** `taskId`, `task` (AnalysisTaskStatus), `isRunning`, `isComplete`, `isFailed`, `isCancelled`, `error`, `elapsedSeconds`

**Actions:**
- `startAnalysis(params?)` -- Starts background analysis, saves task ID to localStorage
- `cancelAnalysis()` -- Cancels running task via API
- `checkForActiveTask()` -- Checks localStorage and server for active/completed tasks
- `clearTask()` -- Resets all state and clears localStorage

**Behavior:**
- Polls task status every 2 seconds (configurable via `pollInterval`)
- Persists task ID to `localStorage` under key `market-analyzer-analysis-task-id`
- On page reload, checks localStorage and resumes polling if task is still running
- On completion, invalidates `deepInsightKeys.all` to refresh insight listing
- Elapsed timer updates every 1 second for UI display
- Guards against race conditions between `startAnalysis` and `checkForActiveTask`
- Callbacks: `onComplete(task)`, `onError(error)`

### `useChat` (use-chat.ts, 362 lines)

General-purpose WebSocket chat:

**State:** `messages`, `isLoading`, `error`, `isConnected`

**Actions:** `sendMessage(options)`, `clearHistory()`, `deleteMessage(id)`, `retry()`, `connect()`, `disconnect()`

**WebSocket Protocol (6 event types):**
- `ack` -- Message received acknowledgment
- `text` -- Streaming text content chunk
- `tool_call` -- MCP tool invocation (name, args)
- `tool_result` -- Tool execution result
- `done` -- Response complete
- `error` -- Error message

**Behavior:**
- Auto-connects on mount, auto-reconnects (max 5 attempts, 3s interval)
- Streaming: Creates placeholder assistant message, appends text chunks in real-time
- Tool calls tracked with pending/complete status
- Connection URL: `NEXT_PUBLIC_WS_URL` or `ws://localhost:8000/api/v1/chat`

### `useInsightChat` (use-insight-conversation.ts)

WebSocket chat scoped to a specific insight conversation:

**Additional features vs useChat:**
- Connects to `/api/v1/conversations/{conversationId}/chat`
- Handles `assistant_chunk`, `modification_proposal`, `research_request` message types
- Modification proposals include field, old/new values, and reasoning
- Research requests include focus area, specific questions, and related symbols
- `isStreaming` flag on messages for UI loading indicators
- `loadInitialMessages()` to hydrate from server-stored conversation history
- Invalidates conversation detail query on `done` to sync with server

### `useInsightConversations` (use-insight-conversation.ts)

CRUD operations for conversations tied to an insight:

**Returns:** `conversations`, `total`, `hasMore`, `createConversation`, `deleteConversation`

### `useDeepInsights` / `useDeepInsight` / `useRecentDeepInsights` (use-deep-insights.ts)

**`useDeepInsights(params?)`** -- Paginated listing with filters (action, insight_type, symbol, limit, offset). Uses `keepPreviousData` for smooth pagination.

**`useDeepInsight(id)`** -- Single insight by ID, conditionally enabled.

**`useRecentDeepInsights(limit=9)`** -- Dashboard-optimized query with 30s staleTime, `EMPTY_RESPONSE` placeholder for instant render, `refetchOnMount: 'always'`.

### `useInsights` / `useInsightAnnotations` (use-insights.ts)

Legacy insight queries plus annotation mutations:

**Mutations with optimistic updates:**
- `useAddAnnotation()` -- Adds annotation, invalidates related queries
- `useUpdateAnnotation()` -- Optimistically updates annotation text, rolls back on error
- `useDeleteAnnotation()` -- Optimistically removes annotation, rolls back on error

### `useStock` / `useStockPriceHistory` / `useStocks` / `useStockInsights` (use-stock.ts)

Stock data queries with error toast notifications and exponential backoff retry:

```typescript
retry: 2,
retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
```

Each hook returns an `isEmpty` flag: `!isLoading && !isError && !data`.

**Helper functions exported:** `formatCurrency()`, `formatLargeNumber()`, `formatPercent()`, `getChangeColorClass()`

### `useSectors` (use-sectors.ts)

Sector performance data with auto-refresh and rotation phase detection:

**Rotation phases:** `early_expansion`, `mid_expansion`, `late_expansion`, `early_contraction`, `late_contraction`, `recovery`

**Transformation helpers:**
- `transformForHeatmap()` -- Maps sectors with consistent naming from SECTOR_LIST
- `transformForTreemap()` -- Maps to `{ name, symbol, size, color }` for proportional viz
- `getPerformanceColor(value)` -- Maps -5% to +5% onto red-white-green gradient
- `getContrastTextColor(bgColor)` -- Luminance-based text color selection
- `formatRotationPhase()` / `getRotationPhaseDescription()` -- Human-readable labels

**SECTOR_LIST constant:** 11 S&P 500 sectors (XLK, XLV, XLF, XLE, XLY, XLI, XLB, XLU, XLRE, XLC, XLP) with assigned colors.

### `useMarketOverview` (use-market-data.ts)

Aggregates data from stocks, insights, and sectors endpoints into a unified market overview. Fetches three endpoints in parallel using `Promise.allSettled()`. Builds market indices from SPY/QQQ/DIA stock data.

### `useSearch` hooks (use-search.ts)

Four search hooks, all with 300ms debounce (200ms for suggestions):
- `useGlobalSearch(query)` -- Stocks + insights combined
- `useStockSearch(query, options?)` -- Stocks with sector/limit filters
- `useInsightSearch(query, options?)` -- Insights with type/severity filters
- `useSearchSuggestions(query)` -- Autocomplete suggestions

`useSearchState()` -- UI state for search modal (open/close, query management).

### `useWatchlist` / `useUpdateWatchlist` (use-watchlist.ts)

Read/write watchlist symbols via the settings API.

### `useRefreshData` (use-refresh-data.ts)

Mutation to trigger ETL data refresh. On success, invalidates stocks, market, market-overview, and tracked-stocks queries.

### `useTrackRecord` / `useOutcomeSummary` / `useOutcomes` / `useInsightOutcome` / `useMonthlyTrend` (use-track-record.ts)

Outcome tracking queries with hierarchical key factories. 5-minute staleTime for aggregate stats, 2-minute for individual outcomes.

### `useStatisticalFeatures` / `useActiveSignals` / `useComputeFeatures` (use-statistical-features.ts)

Statistical feature data for individual symbols (5-min refresh) and cross-watchlist signal scanning (1-min refresh). `useComputeFeatures` is a mutation that triggers server-side computation.

---

## API Client (`lib/api.ts`)

### Base Functions

```typescript
// Generic GET with optional query params
fetchApi<T>(endpoint: string, options?: RequestInit & {
  params?: Record<string, string | number | boolean | undefined>
}): Promise<T>

// POST with JSON body
postApi<T>(endpoint: string, body?: unknown): Promise<T>

// PUT with JSON body
putApi<T>(endpoint: string, body?: unknown): Promise<T>

// DELETE
deleteApi<T>(endpoint: string): Promise<T>
```

**Base URL resolution:**
- Reads `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`)
- Strips trailing `/api/v1` to prevent path duplication

**Error handling:**
- Non-2xx responses throw `ApiError(status, message)`
- `ApiError` extends `Error` with a `status` property
- Body text included in error message for debugging

### API Client Object (`api`)

```typescript
api.health()                              // GET /api/v1/health
api.stocks.list(params?)                  // GET /api/v1/stocks
api.stocks.get(symbol)                    // GET /api/v1/stocks/{symbol}
api.stocks.history(symbol, params?)       // GET /api/v1/stocks/{symbol}/history
api.insights.list(params?)                // GET /api/v1/insights
api.insights.get(id)                      // GET /api/v1/insights/{id}
api.insights.addAnnotation(id, note)      // POST /api/v1/insights/{id}/annotations
api.deepInsights.list(params?)            // GET /api/v1/deep-insights
api.deepInsights.get(id)                  // GET /api/v1/deep-insights/{id}
api.deepInsights.bySymbol(symbol, params?)// GET /api/v1/deep-insights/symbol/{symbol}
api.deepInsights.byType(type, params?)    // GET /api/v1/deep-insights/type/{type}
api.deepInsights.generate(symbols?)       // POST /api/v1/deep-insights/generate
api.deepInsights.autonomous(params?)      // POST /api/v1/deep-insights/autonomous
api.analysis.technical(symbol)            // GET /api/v1/analysis/technical/{symbol}
api.analysis.sectors()                    // GET /api/v1/analysis/sectors
api.analysis.run(symbols?)                // POST /api/v1/analysis/run
api.search(q)                             // GET /api/v1/search?q=...
api.export.stocks(params?)                // GET /api/v1/export/stocks
api.export.insights(params?)              // GET /api/v1/export/insights
api.export.portfolio(params?)             // GET /api/v1/export/portfolio
api.settings.get()                        // GET /api/v1/settings
api.settings.update(key, value)           // PUT /api/v1/settings/{key}
api.settings.watchlist.get()              // GET /api/v1/settings/watchlist
api.settings.watchlist.update(symbols)    // PUT /api/v1/settings/watchlist
refreshData(symbols?)                     // POST /api/v1/data/refresh
knowledgeApi.patterns.list(params?)       // GET /api/v1/knowledge/patterns
knowledgeApi.patterns.get(id)             // GET /api/v1/knowledge/patterns/{id}
knowledgeApi.patterns.matching(params?)   // GET /api/v1/knowledge/patterns/matching
knowledgeApi.themes.list(params?)         // GET /api/v1/knowledge/themes
knowledgeApi.themes.get(id)               // GET /api/v1/knowledge/themes/{id}
```

**Response normalization:** Several endpoints normalize the backend response format. For example, `api.stocks.list()` transforms `{ stocks: [...] }` into `{ items: [...], total: number }`. Similarly, `api.insights.list()` adds pagination metadata (`page`, `per_page`, `total_pages`).

### Legacy API Objects

For backwards compatibility, the following wrappers are also exported:
- `stocksApi` -- Thin wrapper around `api.stocks`
- `insightsApi` -- Wrapper with annotation CRUD and filter mapping
- `analysisApi` -- Wrapper with analyze endpoint
- `chatApi` -- Simple POST to chat endpoint

---

## Real-time Features

### WebSocket Chat

**General Chat** (`useChat`):
- URL: `ws://localhost:8000/api/v1/chat` (configurable via `NEXT_PUBLIC_WS_URL`)
- Auto-connects on component mount
- Auto-reconnects on abnormal closure (max 5 attempts, 3-second interval)
- Normal closure (code 1000) does not trigger reconnection
- Messages are JSON with `{ id, message }` format outbound and `{ type, content, ... }` inbound

**Insight Conversation Chat** (`useInsightChat`):
- URL: `ws://localhost:8000/api/v1/conversations/{conversationId}/chat`
- Same reconnection behavior as general chat
- Additional message types: `modification_proposal` and `research_request`
- On `done`, invalidates the conversation detail query for server sync

### Autonomous Analysis Polling

The `useAnalysisTask` hook manages the full autonomous analysis lifecycle:

1. **Start**: `POST /api/v1/deep-insights/autonomous/start` returns a `task_id`
2. **Persist**: Task ID saved to `localStorage` under `market-analyzer-analysis-task-id`
3. **Poll**: `GET /api/v1/deep-insights/autonomous/status/{taskId}` every 2 seconds
4. **Progress**: UI displays phase name, phase details, progress percentage (0-100%), and elapsed time
5. **Complete**: Invalidates deep insight queries, clears localStorage, calls `onComplete` callback
6. **Failed**: Sets error state, clears localStorage, calls `onError` callback
7. **Cancel**: `POST /api/v1/deep-insights/autonomous/cancel/{taskId}`, updates local state immediately
8. **Resume**: On mount, checks localStorage for saved task ID and resumes polling if task is still running. Also checks server for any active task via `GET /api/v1/deep-insights/autonomous/active`

**Analysis Phases** (5-phase pipeline):
1. MacroScanner -- Macro economic conditions
2. SectorRotator -- Sector rotation analysis
3. OpportunityHunter -- Opportunity identification
4. DeepDive -- Deep analysis of selected opportunities
5. SynthesisLead -- Final synthesis and insight generation

---

## Styling

### Tailwind CSS 4

- Utility-first with `@tailwindcss/postcss` for build-time processing
- Mobile-first responsive breakpoints: `sm` (640px), `md` (768px), `lg` (1024px), `xl` (1280px), `2xl` (1536px)
- Dark mode via `class` strategy (controlled by next-themes)
- Animation utilities from `tw-animate-css`

### shadcn/ui (New York Style)

25+ pre-configured Radix UI components in `components/ui/`:
- **Navigation**: DropdownMenu, Sheet, Tabs, Command
- **Forms**: Input, Textarea, Label, Checkbox, Select
- **Data Display**: Card, Badge, Table, Avatar, Tooltip
- **Feedback**: Dialog, AlertDialog, Progress, Skeleton, Sonner (toasts)
- **Layout**: Separator, ScrollArea, Collapsible

All components built on Radix UI primitives with full ARIA accessibility support.

### `cn()` Utility

```typescript
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

Combines `clsx` for conditional classes with `tailwind-merge` for intelligent conflict resolution (e.g., `cn("px-4", "px-6")` resolves to `"px-6"`).

### Dark Mode

- **ThemeProvider** wraps the app with `attribute="class"`, `defaultTheme="system"`, `enableSystem`
- **ThemeToggle** component cycles between light/dark/system
- Dark mode classes throughout: `dark:bg-*`, `dark:text-*`, `dark:border-*`
- `suppressHydrationWarning` on `<html>` to prevent flash on initial load

---

## Type System

### Core Domain Types (`types/index.ts`)

```typescript
// Stock data
interface Stock {
  symbol: string; name: string; sector?: string;
  current_price?: number; change_percent?: number;
  market_cap?: number; volume?: number;
}

// Price history (OHLCV)
interface PriceHistory {
  date: string; open: number; high: number;
  low: number; close: number; volume: number;
}

// Deep insight (modern)
interface DeepInsight {
  id: number;
  insight_type: DeepInsightType;  // 'opportunity' | 'risk' | 'rotation' | 'macro' | 'divergence' | 'correlation'
  action: InsightAction;           // 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL' | 'WATCH'
  title: string; thesis: string;
  primary_symbol?: string; related_symbols: string[];
  supporting_evidence: AnalystEvidence[];
  confidence: number; time_horizon: string;
  risk_factors: string[]; invalidation_trigger?: string;
  entry_zone?: string; target_price?: string; stop_loss?: string;
  timeframe?: 'swing' | 'position' | 'long-term';
  discovery_context?: DiscoveryContext;
  parent_insight_id?: number; source_conversation_id?: number;
}

// Insight (legacy)
interface Insight {
  id: string; symbol?: string;
  type: InsightType; severity: InsightSeverity;
  title: string; content: string;
  confidence?: number; annotations?: InsightAnnotation[];
}

// Analysis task (autonomous)
interface AnalysisTask {
  id: string; status: string; progress: number;
  current_phase: string | null; phase_name: string | null;
  result_insight_ids: number[] | null;
  market_regime: string | null; top_sectors: string[] | null;
  discovery_summary: string | null;
  elapsed_seconds: number | null;
}

// Pagination wrapper
interface PaginatedResponse<T> {
  items: T[]; total: number;
  page: number; per_page: number; total_pages: number;
}
```

### Chat Types (`types/chat.ts`)

```typescript
interface Message {
  id: string; role: 'user' | 'assistant';
  content: string; timestamp: Date;
  toolCalls?: ToolCall[];
}

interface ToolCall {
  id: string; name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: 'pending' | 'complete';
}

interface ChatState {
  messages: Message[]; isLoading: boolean;
  error: string | null; isConnected: boolean;
}
```

### Extended Types (`lib/types/`)

- **knowledge.ts** -- `KnowledgePattern`, `ConversationTheme`, `KnowledgePatternsResponse`
- **statistical-features.ts** -- `StatisticalFeature`, `ActiveSignal`, `SignalStrength`
- **track-record.ts** -- `TrackRecordStats`, `OutcomeSummary`, `InsightOutcome`, `MonthlyTrendResponse`

---

## Testing

### Playwright Configuration

```typescript
// playwright.config.ts
{
  testDir: './tests',
  fullyParallel: false,     // Sequential execution
  workers: 1,               // Single worker
  retries: 0,               // No retries (set CI retries via env)
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  outputDir: 'test-results',
}
```

### Test Files

| Test File | Coverage |
|-----------|----------|
| `integration.spec.ts` | Core page navigation and basic interactions |
| `api-mocks.spec.ts` | API mock setup and response handling |
| `debug-app.spec.ts` | App startup and general debugging |
| `debug-insights.spec.ts` | Insight rendering and interactions |
| `statistical-signals.spec.ts` | Signal feature display and filtering |
| `outcome-badge.spec.ts` | Outcome badge rendering states |
| `pattern-library.spec.ts` | Pattern library panel interactions |
| `track-record.spec.ts` | Track record dashboard metrics |

### Running Tests

```bash
npx playwright test                           # Run all tests
npx playwright test tests/integration.spec.ts # Single test file
npx playwright test --ui                      # Interactive mode with UI
npx playwright test --headed                  # Visible browser window
npx playwright test --debug                   # Step-through debugger
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | REST API base URL |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000/api/v1/chat` | WebSocket endpoint (general chat) |

Set in `frontend/.env.local` (auto-created by `start.sh`).

---

## Design Patterns

### Server State vs UI State

- **Server state** (TanStack Query): All data fetched from the backend -- stocks, insights, sectors, analysis tasks. Cached, stale-while-revalidated, automatically refetched.
- **UI state** (React.useState): Local-only concerns -- filter selections, tab state, modal open/close, search query text, sidebar collapse.

### Error Handling

1. `ApiError` class with HTTP status code
2. Hooks use `useEffect` to show Sonner toasts on query errors
3. Exponential backoff retry for stock and market data queries
4. Graceful degradation: `Promise.allSettled()` in market overview allows partial data display

### Optimistic Updates

Annotation mutations use the full optimistic update pattern:
1. `onMutate`: Cancel outgoing refetches, snapshot previous data, apply optimistic change
2. `onError`: Rollback to snapshot
3. `onSettled`: Invalidate queries to ensure server consistency

### Feature-based Organization

Components and hooks are organized by feature domain (chat, insights, dashboard, stocks, charts) rather than by technical role. This keeps related code colocated and makes feature additions straightforward.

### Path Alias

TypeScript path alias `@/*` maps to the project root, enabling clean imports:
```typescript
import { Button } from '@/components/ui/button';
import { useChat } from '@/lib/hooks/use-chat';
import type { DeepInsight } from '@/types';
```

---

## Related Documentation

- **[README.md](../README.md)** -- Project overview, quick start, and tech stack
- **[CLAUDE.md](../CLAUDE.md)** -- Developer guidance: commands, architecture summary, key patterns
- **[API.md](../API.md)** -- Detailed REST API and WebSocket endpoint documentation
- **[ARCHITECTURE.md](../ARCHITECTURE.md)** -- System architecture, analysis pipeline, data layer, concurrency model
