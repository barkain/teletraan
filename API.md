# Teletraan API Documentation

## Overview

- **Base URL:** `http://localhost:8000`
- **API Prefix:** `/api/v1/`
- **Authentication:** None required (local development API)
- **Content-Type:** `application/json` (unless otherwise noted)
- **Swagger UI:** `http://localhost:8000/docs`
- **WebSocket:** `ws://localhost:8000/api/v1/chat`

All REST endpoints are prefixed with `/api/v1/`. For example, the health endpoint is at `http://localhost:8000/api/v1/health`.

---

## Health

### GET /api/v1/health

Return health status of the API including database connectivity.

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected",
  "timestamp": "2026-02-07T12:00:00Z"
}
```

| Field       | Type     | Description                              |
|-------------|----------|------------------------------------------|
| `status`    | string   | `"healthy"`                              |
| `version`   | string   | API version                              |
| `database`  | string   | `"connected"` or `"disconnected"`        |
| `timestamp` | datetime | Current server UTC time                  |

**Example:**
```bash
curl http://localhost:8000/api/v1/health
```

---

## Stocks

### GET /api/v1/stocks

List all tracked stocks with pagination and filtering.

**Query Parameters:**

| Parameter     | Type    | Default | Description                        |
|---------------|---------|---------|------------------------------------|
| `skip`        | int     | 0       | Number of records to skip (>= 0)  |
| `limit`       | int     | 50      | Records per page (1-100)           |
| `sector`      | string  | null    | Filter by sector name              |
| `search`      | string  | null    | Search by symbol or company name   |
| `active_only` | bool    | true    | Only return active stocks          |

**Response:**
```json
{
  "stocks": [
    {
      "id": 1,
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "sector": "Technology",
      "industry": "Consumer Electronics",
      "market_cap": 3000000000000.0,
      "is_active": true,
      "created_at": "2026-01-15T10:00:00Z"
    }
  ],
  "total": 42
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/stocks?limit=10&sector=Technology"
```

### GET /api/v1/stocks/sectors/list

Get list of all distinct sectors.

**Response:**
```json
{
  "sectors": ["Communication Services", "Consumer Discretionary", "Technology"]
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/stocks/sectors/list
```

### GET /api/v1/stocks/{symbol}

Get stock details by symbol.

**Path Parameters:**

| Parameter | Type   | Description          |
|-----------|--------|----------------------|
| `symbol`  | string | Stock ticker symbol  |

**Response:**
```json
{
  "id": 1,
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "industry": "Consumer Electronics",
  "market_cap": 3000000000000.0,
  "is_active": true,
  "created_at": "2026-01-15T10:00:00Z"
}
```

**Errors:**
- `404` - Stock not found

**Example:**
```bash
curl http://localhost:8000/api/v1/stocks/AAPL
```

### GET /api/v1/stocks/{symbol}/history

Get price history for a stock.

**Path Parameters:**

| Parameter | Type   | Description         |
|-----------|--------|---------------------|
| `symbol`  | string | Stock ticker symbol |

**Query Parameters:**

| Parameter    | Type | Default | Description                          |
|--------------|------|---------|--------------------------------------|
| `start_date` | date | null    | Start date (YYYY-MM-DD)             |
| `end_date`   | date | null    | End date (YYYY-MM-DD)               |
| `limit`      | int  | 252     | Max records (1-1000, ~1yr trading)   |

**Response:**
```json
[
  {
    "date": "2026-02-06",
    "open": 185.50,
    "high": 187.20,
    "low": 184.80,
    "close": 186.75,
    "volume": 52340000,
    "adjusted_close": 186.75
  }
]
```

**Errors:**
- `404` - Stock not found

**Example:**
```bash
curl "http://localhost:8000/api/v1/stocks/AAPL/history?limit=30&start_date=2026-01-01"
```

---

## Insights

### GET /api/v1/insights

List insights with filtering and pagination.

**Query Parameters:**

| Parameter      | Type   | Default | Description                                                |
|----------------|--------|---------|------------------------------------------------------------|
| `skip`         | int    | 0       | Records to skip (>= 0)                                    |
| `limit`        | int    | 20      | Records per page (1-100)                                   |
| `insight_type` | string | null    | Filter: `pattern`, `anomaly`, `sector`, `technical`, `economic`, `sentiment` |
| `severity`     | string | null    | Filter: `info`, `warning`, `alert`                         |
| `symbol`       | string | null    | Filter by stock symbol                                     |
| `active_only`  | bool   | true    | Only return active, non-expired insights                   |

**Response:**
```json
{
  "insights": [
    {
      "id": 1,
      "insight_type": "pattern",
      "title": "Golden Cross Detected on AAPL",
      "description": "50-day MA crossed above 200-day MA",
      "severity": "info",
      "confidence": 0.85,
      "stock_id": 1,
      "is_active": true,
      "created_at": "2026-02-07T08:00:00Z",
      "expires_at": null
    }
  ],
  "total": 15
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/insights?insight_type=pattern&severity=warning"
```

### GET /api/v1/insights/types

Get available insight types.

**Response:**
```json
{
  "types": ["pattern", "anomaly", "sector", "technical", "economic", "sentiment"]
}
```

### GET /api/v1/insights/severities

Get available severity levels.

**Response:**
```json
{
  "severities": ["info", "warning", "alert"]
}
```

### GET /api/v1/insights/{insight_id}

Get a single insight by ID.

**Errors:**
- `404` - Insight not found

**Example:**
```bash
curl http://localhost:8000/api/v1/insights/1
```

### GET /api/v1/insights/{insight_id}/annotations

Get annotations for an insight.

**Response:**
```json
[
  {
    "id": 1,
    "insight_id": 1,
    "note": "Confirmed by volume analysis",
    "created_at": "2026-02-07T09:00:00Z",
    "updated_at": null
  }
]
```

### POST /api/v1/insights/{insight_id}/annotations

Add an annotation to an insight.

**Request Body:**
```json
{
  "note": "This aligns with the sector rotation thesis"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/insights/1/annotations \
  -H "Content-Type: application/json" \
  -d '{"note": "Confirmed by volume analysis"}'
```

### PUT /api/v1/insights/{insight_id}/annotations/{annotation_id}

Update an existing annotation.

**Request Body:**
```json
{
  "note": "Updated note text"
}
```

### DELETE /api/v1/insights/{insight_id}/annotations/{annotation_id}

Delete an annotation.

**Response:**
```json
{
  "message": "Annotation deleted successfully"
}
```

---

## Deep Insights

AI-generated deep analysis insights from the multi-agent analysis engine.

### GET /api/v1/deep-insights

List deep insights with filtering.

**Query Parameters:**

| Parameter      | Type   | Default | Description                                                         |
|----------------|--------|---------|---------------------------------------------------------------------|
| `limit`        | int    | 20      | Records per page (max 100)                                          |
| `offset`       | int    | 0       | Records to skip                                                     |
| `action`       | string | null    | Filter by action: `BUY`, `SELL`, `HOLD`, `WATCH` (BUY includes STRONG_BUY, SELL includes STRONG_SELL) |
| `insight_type` | string | null    | Filter: `opportunity`, `risk`, `rotation`, `macro`, `divergence`, `correlation` |
| `symbol`       | string | null    | Filter by primary or related symbol                                 |

**Response:**
```json
{
  "items": [
    {
      "id": 1,
      "insight_type": "opportunity",
      "action": "BUY",
      "title": "NVDA Momentum Breakout",
      "thesis": "Strong AI demand cycle supports continued upside...",
      "primary_symbol": "NVDA",
      "related_symbols": ["AMD", "AVGO"],
      "supporting_evidence": [
        {
          "analyst": "TechnicalAnalyst",
          "finding": "RSI shows bullish divergence",
          "confidence": 0.8
        }
      ],
      "confidence": 0.85,
      "time_horizon": "2-4 weeks",
      "risk_factors": ["Sector rotation away from tech", "Valuation concerns"],
      "invalidation_trigger": "Close below $800 support",
      "historical_precedent": "Similar setups in 2024 yielded 12% avg return",
      "analysts_involved": ["TechnicalAnalyst", "SectorAnalyst", "MacroAnalyst"],
      "data_sources": ["yfinance", "technical_analysis"],
      "parent_insight_id": null,
      "source_conversation_id": null,
      "entry_zone": "$850-$870",
      "target_price": "$950",
      "stop_loss": "$800",
      "timeframe": "2-4 weeks",
      "discovery_context": null,
      "created_at": "2026-02-07T08:00:00Z",
      "updated_at": null
    }
  ],
  "total": 25
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/deep-insights?action=BUY&limit=5"
```

### GET /api/v1/deep-insights/{insight_id}

Get a single deep insight by ID.

**Errors:**
- `404` - Deep insight not found

**Example:**
```bash
curl http://localhost:8000/api/v1/deep-insights/1
```

### POST /api/v1/deep-insights/generate

Trigger deep analysis to generate new insights. Runs the multi-agent analysis engine in the background.

**Request Body (optional):**
```json
{
  "symbols": ["AAPL", "MSFT", "NVDA"]
}
```

If no symbols provided, analyzes all tracked symbols.

**Response:**
```json
{
  "message": "Deep analysis started",
  "symbols": ["AAPL", "MSFT", "NVDA"]
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/deep-insights/generate \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["AAPL", "NVDA"]}'
```

---

## Autonomous Analysis Lifecycle

The autonomous analysis system runs a self-guided 5-phase pipeline that discovers market opportunities without requiring specific symbols as input. The lifecycle follows a start-poll-complete pattern.

### Phase Pipeline

1. **MacroScanner** -- Scan macro environment, identify market regime and themes
2. **SectorRotator** -- Analyze sector rotation, find momentum signals
3. **OpportunityHunter** -- Screen for specific stock opportunities
4. **DeepDive** -- Detailed multi-analyst analysis of top candidates
5. **SynthesisLead** -- Rank and produce final actionable insights

### Status Values

| Status                | Progress | Description                            |
|-----------------------|----------|----------------------------------------|
| `pending`             | 0        | Task created, waiting to start         |
| `macro_scan`          | ~10      | Scanning macro environment             |
| `sector_rotation`     | ~25      | Analyzing sector rotation              |
| `opportunity_hunt`    | ~40      | Discovering opportunities              |
| `heatmap_fetch`       | ~45      | Fetching market heatmap data           |
| `heatmap_analysis`    | ~50      | Analyzing market heatmap               |
| `deep_dive`           | ~60      | Deep diving into top candidates        |
| `coverage_evaluation` | ~75      | Evaluating coverage quality            |
| `synthesis`           | ~85      | Synthesizing final insights            |
| `completed`           | 100      | Analysis finished successfully         |
| `failed`              | -1       | Analysis failed with error             |
| `cancelled`           | --       | Cancelled by user                      |

### POST /api/v1/deep-insights/autonomous/start

Start background autonomous analysis. Returns immediately with a task ID for polling.

**Request Body (optional):**
```json
{
  "max_insights": 5,
  "deep_dive_count": 7
}
```

| Field             | Type | Default | Range | Description                         |
|-------------------|------|---------|-------|-------------------------------------|
| `max_insights`    | int  | 5       | 1-20  | Number of final insights to produce |
| `deep_dive_count` | int  | 7       | 1-20  | Number of opportunities to analyze  |

**Response:**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "started",
  "message": "Autonomous analysis started in background"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/deep-insights/autonomous/start \
  -H "Content-Type: application/json" \
  -d '{"max_insights": 5, "deep_dive_count": 7}'
```

### GET /api/v1/deep-insights/autonomous/status/{task_id}

Poll for the status and progress of a running analysis. Frontend should poll every 2 seconds.

**Path Parameters:**

| Parameter | Type   | Description                    |
|-----------|--------|--------------------------------|
| `task_id` | string | UUID returned from `/start`    |

**Response:**
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "deep_dive",
  "progress": 60,
  "current_phase": "deep_dive",
  "phase_details": "Analyzing 7 opportunities in detail",
  "phase_name": "Deep Dive Analysis",
  "result_insight_ids": null,
  "result_analysis_id": null,
  "market_regime": null,
  "top_sectors": null,
  "discovery_summary": null,
  "phases_completed": ["macro_scan", "sector_rotation", "opportunity_hunt"],
  "error_message": null,
  "elapsed_seconds": null,
  "started_at": "2026-02-07T08:00:00Z",
  "completed_at": null
}
```

When `status` is `"completed"`:
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "progress": 100,
  "current_phase": "completed",
  "phase_details": "Generated 5 insights",
  "phase_name": "Analysis Complete",
  "result_insight_ids": [10, 11, 12, 13, 14],
  "result_analysis_id": "analysis_abc123",
  "market_regime": "risk-on",
  "top_sectors": ["Technology", "Consumer Discretionary"],
  "discovery_summary": "Identified 5 actionable opportunities in a risk-on environment...",
  "phases_completed": ["macro_scan", "sector_rotation", "opportunity_hunt", "deep_dive", "synthesis"],
  "error_message": null,
  "elapsed_seconds": 145.3,
  "started_at": "2026-02-07T08:00:00Z",
  "completed_at": "2026-02-07T08:02:25Z"
}
```

**Errors:**
- `404` - Analysis task not found

**Example:**
```bash
curl http://localhost:8000/api/v1/deep-insights/autonomous/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### GET /api/v1/deep-insights/autonomous/active

Check if an analysis is currently running. Use on page load to resume tracking.

**Response:** Same as status endpoint, or `null` if no active analysis.

**Example:**
```bash
curl http://localhost:8000/api/v1/deep-insights/autonomous/active
```

### GET /api/v1/deep-insights/autonomous/recent

Get the most recently completed analysis task. Use to show results when returning to the page.

**Response:** Same as status endpoint, or `null` if no completed analysis exists.

**Example:**
```bash
curl http://localhost:8000/api/v1/deep-insights/autonomous/recent
```

### POST /api/v1/deep-insights/autonomous/cancel/{task_id}

Cancel a running analysis task. Sets status to `cancelled` at the next checkpoint.

**Path Parameters:**

| Parameter | Type   | Description           |
|-----------|--------|-----------------------|
| `task_id` | string | UUID of task to cancel |

**Response:**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "cancelled",
  "message": "Analysis cancelled successfully"
}
```

If the task is already completed or failed:
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "message": "Task cannot be cancelled (status: completed)"
}
```

**Errors:**
- `404` - Analysis task not found

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/deep-insights/autonomous/cancel/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### POST /api/v1/deep-insights/autonomous (Synchronous)

Run autonomous analysis synchronously (blocks until complete). For long-running analysis, prefer the async start/poll endpoints above.

**Request Body (optional):**
```json
{
  "max_insights": 5,
  "deep_dive_count": 7
}
```

**Response:**
```json
{
  "analysis_id": "analysis_abc123",
  "status": "complete",
  "insights_count": 5,
  "elapsed_seconds": 142.5,
  "discovery_summary": "Identified 5 opportunities in a risk-on market...",
  "market_regime": "risk-on",
  "top_sectors": ["Technology", "Consumer Discretionary"],
  "phases_completed": ["macro_scan", "sector_rotation", "opportunity_hunt", "deep_dive", "synthesis"],
  "errors": []
}
```

### POST /api/v1/deep-insights/autonomous/more

Get additional insights beyond the initial batch (pagination for "Load More").

**Request Body:**
```json
{
  "offset": 5,
  "limit": 5
}
```

**Response:**
```json
{
  "items": [ /* DeepInsightResponse objects */ ],
  "offset": 5,
  "limit": 5,
  "has_more": true
}
```

### GET /api/v1/deep-insights/discovery-context/{analysis_id}

Get the discovery context for an analysis showing how opportunities were found.

**Response:**
```json
{
  "analysis_id": "analysis_abc123",
  "context": {
    "macro_regime": "risk-on",
    "opportunity_type": "momentum_breakout",
    "analysis_type": "autonomous_discovery",
    "data_sources": ["macro_regime:risk-on", "analysis_type:autonomous_discovery"]
  }
}
```

**Errors:**
- `404` - Discovery context not found

---

## Analysis

### GET /api/v1/analysis/technical/{symbol}

Get technical analysis for a stock. Returns indicator values and signals including RSI, MACD, Bollinger Bands, Stochastic, ATR, and moving averages.

**Path Parameters:**

| Parameter | Type   | Description         |
|-----------|--------|---------------------|
| `symbol`  | string | Stock ticker symbol |

**Query Parameters:**

| Parameter  | Type | Default | Description                    |
|------------|------|---------|--------------------------------|
| `lookback` | int  | 100     | Periods to analyze (20-500)    |

**Response:**
```json
{
  "symbol": "AAPL",
  "analyzed_at": "2026-02-07T12:00:00Z",
  "overall_signal": "bullish",
  "confidence": 0.72,
  "bullish_count": 4,
  "bearish_count": 1,
  "neutral_count": 2,
  "indicators": [
    {
      "indicator": "RSI",
      "value": 62.5,
      "signal": "bullish",
      "strength": 0.65
    }
  ],
  "crossovers": [
    {
      "type": "golden_cross",
      "date": "2026-02-01"
    }
  ]
}
```

**Errors:**
- `404` - Stock not found or no price data

**Example:**
```bash
curl "http://localhost:8000/api/v1/analysis/technical/AAPL?lookback=200"
```

### GET /api/v1/analysis/patterns/{symbol}

Get detected chart patterns for a stock. Detects double tops/bottoms, head and shoulders, golden/death crosses, breakouts, and continuation patterns.

**Path Parameters:**

| Parameter | Type   | Description         |
|-----------|--------|---------------------|
| `symbol`  | string | Stock ticker symbol |

**Query Parameters:**

| Parameter        | Type  | Default | Description                     |
|------------------|-------|---------|---------------------------------|
| `min_confidence` | float | 0.6     | Minimum pattern confidence (0-1)|

**Response:**
```json
{
  "symbol": "AAPL",
  "analyzed_at": "2026-02-07T12:00:00Z",
  "total_patterns": 3,
  "bullish_patterns": 2,
  "bearish_patterns": 1,
  "neutral_patterns": 0,
  "overall_bias": "bullish",
  "confidence": 0.75,
  "patterns": [
    {
      "pattern_type": "golden_cross",
      "start_date": "2026-01-15",
      "end_date": "2026-02-01",
      "confidence": 0.82,
      "price_target": 195.00,
      "stop_loss": 175.00,
      "description": "50-day MA crossed above 200-day MA",
      "supporting_data": {}
    }
  ],
  "support_levels": [{"price": 180.0, "strength": "strong"}],
  "resistance_levels": [{"price": 195.0, "strength": "moderate"}]
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/analysis/patterns/AAPL?min_confidence=0.7"
```

### GET /api/v1/analysis/anomalies/{symbol}

Get detected anomalies for a stock. Detects volume spikes, price gaps, volatility surges, and unusual price moves.

**Response:**
```json
{
  "symbol": "AAPL",
  "analyzed_at": "2026-02-07T12:00:00Z",
  "total_anomalies": 2,
  "anomalies_by_severity": {"info": 1, "warning": 1, "alert": 0},
  "anomalies": [
    {
      "anomaly_type": "volume_spike",
      "detected_at": "2026-02-06T16:00:00Z",
      "severity": "warning",
      "value": 85000000.0,
      "expected_range": [40000000.0, 60000000.0],
      "z_score": 3.2,
      "description": "Volume 142% above 20-day average"
    }
  ]
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/analysis/anomalies/AAPL
```

### GET /api/v1/analysis/sectors

Get sector rotation analysis. Analyzes sector performance, relative strength, rotation patterns, and market cycle phase.

**Response:**
```json
{
  "timestamp": "2026-02-07T12:00:00Z",
  "market_phase": "expansion",
  "phase_description": "Broad market advance with cyclical leadership",
  "expected_leaders": ["Technology", "Consumer Discretionary"],
  "sector_metrics": {
    "XLK": {
      "name": "Technology",
      "daily_return": 0.012,
      "weekly_return": 0.035,
      "monthly_return": 0.08,
      "quarterly_return": 0.15,
      "ytd_return": 0.06,
      "relative_strength": 1.25,
      "momentum_score": 0.78,
      "volatility": 0.18,
      "volume_trend": "increasing"
    }
  },
  "rotation_analysis": {
    "rotation_detected": true,
    "rotation_type": "risk-on",
    "leading_sectors": [{"symbol": "XLK", "name": "Technology"}],
    "lagging_sectors": [{"symbol": "XLU", "name": "Utilities"}],
    "signals": [{"type": "momentum_shift", "description": "..."}],
    "cyclical_vs_defensive": {"cyclical": 0.65, "defensive": 0.35}
  },
  "insights": [
    {
      "type": "rotation",
      "priority": "high",
      "title": "Technology sector outperformance accelerating",
      "description": "XLK leading S&P 500 by 3.2% over past month",
      "action": "Overweight technology exposure",
      "sectors": [],
      "warnings": [],
      "divergences": []
    }
  ]
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/analysis/sectors
```

### POST /api/v1/analysis/run

Trigger analysis run for specified symbols or all tracked stocks. Runs in background.

**Request Body (optional):**
```json
{
  "symbols": ["AAPL", "MSFT"]
}
```

**Response:**
```json
{
  "status": "started",
  "message": "Analysis started for 2 symbols",
  "symbols": ["AAPL", "MSFT"],
  "started_at": "2026-02-07T12:00:00Z"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/analysis/run \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["AAPL", "NVDA"]}'
```

### GET /api/v1/analysis/summary

Get summary of latest analysis results.

**Response:**
```json
{
  "last_run": "2026-02-07T08:00:00Z",
  "stocks_analyzed": 8,
  "patterns_detected": 12,
  "anomalies_detected": 5,
  "insights_generated": 20,
  "patterns_by_type": {"detected": 12},
  "anomalies_by_severity": {"info": 2, "warning": 2, "alert": 1},
  "insights_by_type": {"pattern": 12, "anomaly": 5, "technical": 3}
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/analysis/summary
```

---

## Chat

### WebSocket: ws://localhost:8000/api/v1/chat

Real-time streaming LLM chat with market data tool calling.

#### Connection

Connect via WebSocket. A unique `client_id` is assigned server-side.

```javascript
const ws = new WebSocket("ws://localhost:8000/api/v1/chat");
```

#### Message Protocol

**Client sends:**
```json
{
  "id": "msg-123",
  "message": "What is the current technical outlook for AAPL?"
}
```

| Field     | Type   | Required | Description                    |
|-----------|--------|----------|--------------------------------|
| `id`      | string | No       | Message ID (auto-generated if omitted) |
| `message` | string | Yes      | User's question                |

**Server sends (in order):**

1. **Acknowledgment:**
```json
{
  "type": "ack",
  "message_id": "msg-123"
}
```

2. **Text chunks (streamed):**
```json
{
  "type": "text",
  "content": "Based on the technical analysis...",
  "message_id": "msg-123"
}
```

3. **Tool call (when agent uses a tool):**
```json
{
  "type": "tool_call",
  "tool_name": "get_stock_price",
  "tool_args": {"symbol": "AAPL"},
  "message_id": "msg-123"
}
```

4. **Tool result:**
```json
{
  "type": "tool_result",
  "tool_name": "get_stock_price",
  "tool_result": {"price": 186.75, "change": 1.2},
  "message_id": "msg-123"
}
```

5. **Done signal:**
```json
{
  "type": "done",
  "message_id": "msg-123"
}
```

6. **Error (if something fails):**
```json
{
  "type": "error",
  "error": "Error message",
  "message_id": "msg-123"
}
```

#### Message Types Summary

| Type          | Direction      | Description                              |
|---------------|----------------|------------------------------------------|
| `ack`         | Server -> Client | Message received acknowledgment          |
| `text`        | Server -> Client | Streamed text response chunk             |
| `tool_call`   | Server -> Client | Agent is calling a market data tool      |
| `tool_result` | Server -> Client | Result from a tool call                  |
| `done`        | Server -> Client | Response complete                        |
| `error`       | Server -> Client | Error occurred                           |

### POST /api/v1/chat/clear

Clear chat history for all sessions.

**Response:**
```json
{
  "status": "cleared",
  "message": "Chat history has been cleared"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/chat/clear
```

---

## Data

### POST /api/v1/data/refresh

Refresh stock data from Yahoo Finance. Fetches stock info and 30 days of price history. Also triggers analysis and deep analysis on updated symbols.

**Request Body (optional):**
```json
{
  "symbols": ["AAPL", "MSFT", "GOOGL"]
}
```

If no symbols provided, defaults to: `SPY`, `QQQ`, `AAPL`, `MSFT`, `GOOGL`, `NVDA`, `META`, `AMZN`.

**Response:**
```json
{
  "status": "success",
  "symbols_updated": ["AAPL", "MSFT", "GOOGL"],
  "records_added": 66,
  "insights_generated": 8,
  "deep_insights_generated": 3,
  "errors": null,
  "analysis_error": null
}
```

| `status` value | Description                        |
|----------------|------------------------------------|
| `success`      | All symbols updated                |
| `partial`      | Some symbols failed                |
| `failed`       | No symbols updated                 |

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/data/refresh \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["AAPL", "NVDA"]}'
```

### POST /api/v1/data/deep-analysis

Trigger deep multi-agent analysis directly.

**Request Body (optional):**
```json
["AAPL", "MSFT"]
```

**Response:**
```json
{
  "status": "success",
  "insights_generated": 3
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/data/deep-analysis \
  -H "Content-Type: application/json" \
  -d '["AAPL", "NVDA"]'
```

---

## Settings

### GET /api/v1/settings

Get all user settings.

**Response:**
```json
{
  "settings": {
    "theme": "dark",
    "refresh_interval": 300,
    "watchlist_symbols": ["AAPL", "MSFT", "GOOGL"]
  }
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/settings
```

### GET /api/v1/settings/{key}

Get a specific setting by key.

**Response:**
```json
{
  "key": "theme",
  "value": "dark"
}
```

**Errors:**
- `404` - Setting not found

### PUT /api/v1/settings/{key}

Update a specific setting.

**Request Body:**
```json
{
  "value": "light"
}
```

**Response:**
```json
{
  "key": "theme",
  "value": "light",
  "updated_at": "2026-02-07T12:00:00Z"
}
```

**Example:**
```bash
curl -X PUT http://localhost:8000/api/v1/settings/theme \
  -H "Content-Type: application/json" \
  -d '{"value": "light"}'
```

### POST /api/v1/settings/reset

Reset all settings to defaults.

**Response:**
```json
{
  "success": true,
  "message": "Settings have been reset to defaults",
  "settings": { /* default settings */ }
}
```

### GET /api/v1/settings/watchlist

Get the current watchlist settings.

**Response:**
```json
{
  "symbols": ["AAPL", "GOOGL", "MSFT", "AMZN", "NVDA"],
  "last_refresh": "2026-02-07T08:00:00Z"
}
```

### PUT /api/v1/settings/watchlist

Replace the entire watchlist.

**Request Body:**
```json
{
  "symbols": ["AAPL", "MSFT", "NVDA", "META"]
}
```

**Response:**
```json
{
  "symbols": ["AAPL", "MSFT", "NVDA", "META"],
  "last_refresh": "2026-02-07T12:00:00Z"
}
```

### POST /api/v1/settings/watchlist/add

Add symbols to the watchlist.

**Request Body:**
```json
["TSLA", "AMD"]
```

**Response:**
```json
{
  "watchlist": ["AAPL", "MSFT", "NVDA", "TSLA", "AMD"]
}
```

### POST /api/v1/settings/watchlist/remove

Remove symbols from the watchlist.

**Request Body:**
```json
["TSLA"]
```

**Response:**
```json
{
  "watchlist": ["AAPL", "MSFT", "NVDA", "AMD"]
}
```

---

## Conversations

Conversational exploration of DeepInsights with streaming AI responses, modification proposals, and research requests.

### POST /api/v1/insights/{insight_id}/conversations

Start a new conversation for a deep insight.

**Request Body (optional):**
```json
{
  "title": "Discussion about NVDA momentum thesis"
}
```

**Response:**
```json
{
  "id": 1,
  "deep_insight_id": 5,
  "title": "Discussion: NVDA Momentum Breakout",
  "status": "active",
  "message_count": 0,
  "modification_count": 0,
  "created_at": "2026-02-07T12:00:00Z",
  "updated_at": "2026-02-07T12:00:00Z",
  "closed_at": null,
  "summary": null
}
```

**Errors:**
- `404` - Insight not found

### GET /api/v1/insights/{insight_id}/conversations

List all conversations for an insight.

**Query Parameters:**

| Parameter | Type   | Default | Description                           |
|-----------|--------|---------|---------------------------------------|
| `limit`   | int    | 20      | Max results (max 100)                 |
| `offset`  | int    | 0       | Pagination offset                     |
| `status`  | string | null    | Filter: `active`, `resolved`, `archived` |

**Response:**
```json
{
  "items": [ /* ConversationResponse objects */ ],
  "total": 3,
  "has_more": false
}
```

### GET /api/v1/conversations

List all conversations across all insights.

**Query Parameters:** Same as above.

### GET /api/v1/conversations/{conversation_id}

Get a conversation with its recent messages, pending modifications, and research context.

**Query Parameters:**

| Parameter       | Type | Default | Description                |
|-----------------|------|---------|----------------------------|
| `message_limit` | int  | 50      | Max messages to include (max 200) |

**Response:**
```json
{
  "id": 1,
  "deep_insight_id": 5,
  "title": "Discussion: NVDA Momentum Breakout",
  "status": "active",
  "message_count": 12,
  "modification_count": 2,
  "created_at": "2026-02-07T12:00:00Z",
  "updated_at": "2026-02-07T12:30:00Z",
  "closed_at": null,
  "summary": null,
  "research_context": null,
  "recent_messages": [
    {
      "id": 1,
      "conversation_id": 1,
      "role": "user",
      "content": "What if the AI demand cycle slows?",
      "content_type": "text",
      "metadata_": {},
      "parent_message_id": null,
      "created_at": "2026-02-07T12:05:00Z"
    }
  ],
  "pending_modifications": [
    {
      "id": 1,
      "deep_insight_id": 5,
      "conversation_id": 1,
      "message_id": 2,
      "modification_type": "update",
      "field_modified": "risk_factors",
      "previous_value": {"value": ["Sector rotation"]},
      "new_value": {"value": ["Sector rotation", "AI demand slowdown"]},
      "reason": "User raised valid concern about demand cycle",
      "status": "pending",
      "approved_at": null,
      "rejected_reason": null,
      "created_at": "2026-02-07T12:06:00Z",
      "updated_at": "2026-02-07T12:06:00Z"
    }
  ]
}
```

### PATCH /api/v1/conversations/{conversation_id}

Update a conversation's title or status.

**Request Body:**
```json
{
  "title": "Updated title",
  "status": "resolved"
}
```

### DELETE /api/v1/conversations/{conversation_id}

Delete a conversation and all its messages.

**Response:**
```json
{
  "status": "deleted",
  "conversation_id": 1
}
```

### WebSocket: ws://localhost:8000/api/v1/conversations/{conversation_id}/chat

Streaming chat for insight conversations with modification proposals and research requests.

**Client sends:**
```json
{
  "id": "msg-456",
  "message": "What if interest rates rise faster than expected?"
}
```

**Server sends:**

| Type                    | Description                                              |
|-------------------------|----------------------------------------------------------|
| `ack`                   | Message received                                         |
| `assistant_chunk`       | Streamed text response chunk                             |
| `modification_proposal` | AI proposes a change to the insight                      |
| `research_request`      | AI requests follow-up research                           |
| `done`                  | Response complete                                        |
| `error`                 | Error occurred                                           |

**Modification proposal message:**
```json
{
  "type": "modification_proposal",
  "data": {
    "modification_id": 5,
    "field": "risk_factors",
    "old_value": ["Sector rotation"],
    "new_value": ["Sector rotation", "Interest rate sensitivity"],
    "reasoning": "Rising rates would compress tech valuations",
    "modification_type": "update"
  },
  "message_id": "msg-456"
}
```

**Research request message:**
```json
{
  "type": "research_request",
  "data": {
    "research_id": 3,
    "focus_area": "NVDA interest rate sensitivity analysis",
    "specific_questions": ["Historical correlation between NVDA and 10Y yield"],
    "related_symbols": ["NVDA", "TLT"],
    "research_type": "quantitative"
  },
  "message_id": "msg-456"
}
```

---

## Insight Modifications

Manage modifications to DeepInsights that arise from conversations.

### GET /api/v1/insights/{insight_id}/modifications

List all modifications for a specific insight.

**Query Parameters:**

| Parameter | Type   | Default | Description                                  |
|-----------|--------|---------|----------------------------------------------|
| `status`  | string | null    | Filter: `PENDING`, `APPROVED`, `REJECTED`    |
| `limit`   | int    | 50      | Max results (max 100)                        |
| `offset`  | int    | 0       | Pagination offset                            |

**Response:**
```json
{
  "items": [ /* InsightModificationResponse objects */ ],
  "total": 5,
  "has_more": false
}
```

### POST /api/v1/insights/{insight_id}/modifications

Create a proposed modification for an insight (status: `PENDING`).

**Request Body:**
```json
{
  "modification_type": "update",
  "field_modified": "confidence",
  "new_value": 0.75,
  "reason": "New data suggests lower confidence",
  "conversation_id": 1,
  "message_id": 5
}
```

**Modifiable fields:** `thesis`, `confidence`, `action`, `time_horizon`, `risk_factors`, `related_symbols`, `invalidation_trigger`, `title`, `supporting_evidence`

**Response:** `201 Created` with the modification object.

**Errors:**
- `404` - Insight not found
- `400` - Field not modifiable or conversation not found

### GET /api/v1/modifications/pending

List all pending modifications across all insights (queue view).

**Query Parameters:**

| Parameter    | Type | Default | Description            |
|--------------|------|---------|------------------------|
| `limit`      | int  | 50      | Max results (max 100)  |
| `offset`     | int  | 0       | Pagination offset      |
| `insight_id` | int  | null    | Filter by insight ID   |

### GET /api/v1/modifications/{modification_id}

Get a single modification by ID.

### PATCH /api/v1/modifications/{modification_id}/approve

Approve a pending modification and apply it to the insight immediately.

**Request Body (optional):**
```json
{
  "reason": "Approved after review"
}
```

**Errors:**
- `400` - Not in PENDING status

### PATCH /api/v1/modifications/{modification_id}/reject

Reject a pending modification.

**Request Body:**
```json
{
  "reason": "Insufficient evidence for change"
}
```

**Errors:**
- `400` - Not in PENDING status

### DELETE /api/v1/modifications/{modification_id}

Delete a pending modification. Only PENDING modifications can be deleted.

**Response:** `204 No Content`

**Errors:**
- `400` - Not in PENDING status

---

## Knowledge

### GET /api/v1/knowledge/patterns

List validated knowledge patterns.

**Query Parameters:**

| Parameter          | Type   | Default | Description                          |
|--------------------|--------|---------|--------------------------------------|
| `pattern_type`     | string | null    | Filter by pattern type               |
| `min_success_rate` | float  | 0.5     | Minimum success rate threshold (0-1) |
| `is_active`        | bool   | true    | Filter by active status              |
| `limit`            | int    | 20      | Max results (max 100)                |
| `offset`           | int    | 0       | Pagination offset                    |

**Response:**
```json
{
  "items": [
    {
      "id": "uuid-string",
      "pattern_type": "oversold_bounce",
      "name": "RSI Oversold Reversal",
      "description": "Stocks with RSI below 30 tend to bounce within 5 days",
      "trigger_conditions": {"rsi_below": 30},
      "success_rate": 0.72,
      "sample_size": 45,
      "avg_return": 3.5,
      "is_active": true,
      "created_at": "2026-01-15T10:00:00Z",
      "updated_at": "2026-02-07T08:00:00Z"
    }
  ],
  "total": 12
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/knowledge/patterns?min_success_rate=0.7"
```

### GET /api/v1/knowledge/patterns/matching

Get patterns matching current market conditions.

**Query Parameters:**

| Parameter          | Type       | Description                    |
|--------------------|------------|--------------------------------|
| `symbols`          | list[str]  | Symbols to check               |
| `rsi`              | float      | Current RSI value              |
| `vix`              | float      | Current VIX level              |
| `volume_surge_pct` | float      | Volume surge percentage        |
| `sector_momentum`  | float      | Sector momentum score          |

**Example:**
```bash
curl "http://localhost:8000/api/v1/knowledge/patterns/matching?rsi=28&vix=25"
```

### GET /api/v1/knowledge/patterns/{pattern_id}

Get a specific knowledge pattern by UUID.

### GET /api/v1/knowledge/themes

List active conversation themes.

**Query Parameters:**

| Parameter       | Type   | Default | Description                          |
|-----------------|--------|---------|--------------------------------------|
| `theme_type`    | string | null    | Filter by theme type                 |
| `min_relevance` | float  | 0.3     | Minimum relevance threshold (0-1)    |
| `sector`        | string | null    | Filter by related sector             |
| `limit`         | int    | 20      | Max results (max 100)                |
| `offset`        | int    | 0       | Pagination offset                    |

### GET /api/v1/knowledge/themes/{theme_id}

Get a specific conversation theme by UUID.

### GET /api/v1/knowledge/track-record

Get historical track record of insight accuracy.

**Query Parameters:**

| Parameter       | Type   | Default | Description                    |
|-----------------|--------|---------|--------------------------------|
| `insight_type`  | string | null    | Filter by insight type         |
| `action_type`   | string | null    | Filter by action type          |
| `lookback_days` | int    | 90      | Days to look back (1-365)      |

**Response:**
```json
{
  "total_insights": 50,
  "successful": 35,
  "success_rate": 0.7,
  "by_type": {
    "opportunity": {
      "total": 30,
      "successful": 22,
      "success_rate": 0.7333,
      "avg_return": 5.2
    }
  },
  "by_action": {
    "BUY": {
      "total": 25,
      "successful": 18,
      "success_rate": 0.72,
      "avg_return": 6.1
    }
  },
  "avg_return_successful": 5.8,
  "avg_return_failed": -2.3
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/knowledge/track-record?lookback_days=180"
```

---

## Outcomes

Track and validate insight prediction outcomes.

### GET /api/v1/outcomes

List insight outcomes with optional filtering.

**Query Parameters:**

| Parameter   | Type   | Default | Description                                    |
|-------------|--------|---------|------------------------------------------------|
| `status`    | string | null    | Filter: `tracking` or `completed`              |
| `validated` | bool   | null    | Filter by whether thesis was validated          |
| `limit`     | int    | 50      | Max results (1-200)                            |
| `offset`    | int    | 0       | Pagination offset                              |

**Response:**
```json
[
  {
    "id": "uuid-string",
    "insight_id": 5,
    "tracking_status": "tracking",
    "tracking_start_date": "2026-02-01",
    "tracking_end_date": "2026-03-01",
    "initial_price": 185.50,
    "current_price": 192.30,
    "final_price": null,
    "actual_return_pct": null,
    "predicted_direction": "bullish",
    "thesis_validated": null,
    "outcome_category": null,
    "validation_notes": null,
    "days_remaining": 22
  }
]
```

### GET /api/v1/outcomes/summary

Get aggregate statistics for insight outcomes.

**Query Parameters:**

| Parameter       | Type | Default | Description                    |
|-----------------|------|---------|--------------------------------|
| `lookback_days` | int  | 90      | Days to look back (1-365)      |

**Response:**
```json
{
  "total_tracked": 45,
  "currently_tracking": 12,
  "completed": 33,
  "success_rate": 0.697,
  "avg_return_when_correct": 5.8,
  "avg_return_when_wrong": -2.1,
  "by_direction": {
    "bullish": {"total": 25, "correct": 18},
    "bearish": {"total": 8, "correct": 5}
  },
  "by_category": {
    "strong_win": 10,
    "modest_win": 13,
    "modest_loss": 7,
    "strong_loss": 3
  }
}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/outcomes/summary
```

### GET /api/v1/outcomes/{outcome_id}

Get a specific insight outcome by UUID.

### GET /api/v1/outcomes/insight/{insight_id}

Get the outcome for a specific insight.

**Errors:**
- `404` - No outcome found for this insight

### POST /api/v1/outcomes/start

Start tracking an insight's prediction outcome.

**Request Body:**
```json
{
  "insight_id": 5,
  "symbol": "NVDA",
  "predicted_direction": "bullish",
  "tracking_days": 30
}
```

**Response:** The created InsightOutcome object.

**Errors:**
- `400` - Validation error
- `500` - Failed to start tracking

### POST /api/v1/outcomes/check

Trigger a check of all active outcome tracking. Updates current prices and evaluates outcomes that reached their tracking end date. Designed to be called periodically by a scheduler.

**Response:**
```json
{
  "checked": 12,
  "completed": 3,
  "updated": 12
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/outcomes/check
```

---

## Export

### GET /api/v1/export/stocks/{symbol}/csv

Export stock price history as CSV file download.

**Query Parameters:**

| Parameter    | Type | Description              |
|--------------|------|--------------------------|
| `start_date` | date | Start date (YYYY-MM-DD)  |
| `end_date`   | date | End date (YYYY-MM-DD)    |

**Response:** CSV file download with columns: Date, Open, High, Low, Close, Volume, Adjusted Close

**Example:**
```bash
curl -o AAPL_prices.csv "http://localhost:8000/api/v1/export/stocks/AAPL/csv?start_date=2026-01-01"
```

### GET /api/v1/export/stocks/{symbol}/json

Export stock data as JSON file download.

**Query Parameters:**

| Parameter            | Type | Default | Description                         |
|----------------------|------|---------|-------------------------------------|
| `start_date`         | date | null    | Start date                          |
| `end_date`           | date | null    | End date                            |
| `include_indicators` | bool | false   | Include technical indicators        |

**Example:**
```bash
curl -o AAPL_data.json "http://localhost:8000/api/v1/export/stocks/AAPL/json?include_indicators=true"
```

### GET /api/v1/export/insights/csv

Export insights as CSV file download.

**Query Parameters:**

| Parameter      | Type   | Description                  |
|----------------|--------|------------------------------|
| `insight_type` | string | Filter by insight type       |
| `severity`     | string | Filter by severity           |
| `symbol`       | string | Filter by stock symbol       |

### GET /api/v1/export/insights/json

Export insights as JSON file download.

**Query Parameters:**

| Parameter             | Type   | Default | Description                  |
|-----------------------|--------|---------|------------------------------|
| `insight_type`        | string | null    | Filter by insight type       |
| `severity`            | string | null    | Filter by severity           |
| `symbol`              | string | null    | Filter by stock symbol       |
| `include_annotations` | bool   | true    | Include annotation data      |

### GET /api/v1/export/analysis/{symbol}

Export complete analysis for a stock including price history, indicators, and insights.

**Query Parameters:**

| Parameter            | Type   | Default | Description                        |
|----------------------|--------|---------|------------------------------------|
| `format`             | string | `json`  | `json` or `csv`                    |
| `start_date`         | date   | null    | Start date                         |
| `end_date`           | date   | null    | End date                           |
| `include_indicators` | bool   | true    | Include technical indicators       |
| `include_insights`   | bool   | true    | Include insights                   |

**Example:**
```bash
curl -o AAPL_analysis.json "http://localhost:8000/api/v1/export/analysis/AAPL?format=json&include_indicators=true"
```

---

## Search

### GET /api/v1/search

Unified search across stocks and insights. Results are scored by relevance with exact matches ranked higher.

**Query Parameters:**

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `q`       | string | Yes      | Search query (min 1 char)|
| `limit`   | int    | No       | Max results (1-100, default 20) |

**Response:**
```json
{
  "stocks": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "sector": "Technology",
      "score": 1.0
    }
  ],
  "insights": [
    {
      "id": 1,
      "title": "Apple momentum breakout",
      "insight_type": "pattern",
      "score": 0.85
    }
  ],
  "total_stocks": 1,
  "total_insights": 3
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/search?q=apple&limit=10"
```

### GET /api/v1/search/stocks

Search stocks with optional sector filter.

**Query Parameters:**

| Parameter     | Type   | Required | Description                   |
|---------------|--------|----------|-------------------------------|
| `q`           | string | Yes      | Search query                  |
| `sector`      | string | No       | Filter by sector              |
| `active_only` | bool   | No       | Only active stocks (default true) |
| `limit`       | int    | No       | Max results (1-100, default 20) |

**Response:**
```json
{
  "stocks": [ /* stock results */ ],
  "total": 5,
  "query": "tech"
}
```

### GET /api/v1/search/insights

Search insights with filters.

**Query Parameters:**

| Parameter      | Type   | Required | Description                          |
|----------------|--------|----------|--------------------------------------|
| `q`            | string | Yes      | Search query                         |
| `insight_type` | string | No       | Filter by type                       |
| `severity`     | string | No       | Filter by severity                   |
| `active_only`  | bool   | No       | Only active insights (default true)  |
| `limit`        | int    | No       | Max results (1-100, default 20)      |

### GET /api/v1/search/suggestions

Get quick search suggestions for autocomplete.

**Query Parameters:**

| Parameter | Type   | Required | Description                    |
|-----------|--------|----------|--------------------------------|
| `q`       | string | Yes      | Partial query (min 1 char)     |
| `limit`   | int    | No       | Max suggestions (1-10, default 5) |

**Response:**
```json
{
  "suggestions": [
    {"type": "stock", "symbol": "AAPL", "name": "Apple Inc."},
    {"type": "stock", "symbol": "AMZN", "name": "Amazon.com Inc."}
  ]
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/search/suggestions?q=ap&limit=5"
```

---

## Statistical Features

### GET /api/v1/features/signals

Get all active signals across the watchlist.

**Query Parameters:**

| Parameter      | Type   | Default | Description                                              |
|----------------|--------|---------|----------------------------------------------------------|
| `signal_type`  | string | null    | Filter: `bullish`, `bearish`, `oversold`, `overbought`   |
| `min_strength` | string | null    | Minimum strength: `weak`, `moderate`, `strong`           |

**Response:**
```json
{
  "signals": [
    {
      "symbol": "AAPL",
      "feature_type": "momentum_roc_5d",
      "signal": "bullish",
      "value": 3.5,
      "strength": "strong"
    }
  ],
  "count": 5,
  "as_of": "2026-02-07T12:00:00Z"
}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/features/signals?min_strength=strong"
```

### GET /api/v1/features/{symbol}

Get all statistical features for a symbol.

**Query Parameters:**

| Parameter          | Type | Default | Description                          |
|--------------------|------|---------|--------------------------------------|
| `calculation_date` | date | null    | Date for features (latest if omitted)|

**Response:**
```json
{
  "symbol": "AAPL",
  "features": [
    {
      "id": 1,
      "symbol": "AAPL",
      "feature_type": "momentum_roc_5d",
      "value": 2.3,
      "percentile": 72.5,
      "signal": "bullish",
      "calculation_date": "2026-02-07"
    }
  ],
  "calculation_date": "2026-02-07"
}
```

**Errors:**
- `404` - No features found for symbol

### GET /api/v1/features/{symbol}/{feature_type}

Get a specific statistical feature for a symbol.

**Path Parameters:**

| Parameter      | Type   | Description                                      |
|----------------|--------|--------------------------------------------------|
| `symbol`       | string | Stock ticker symbol                              |
| `feature_type` | string | Feature type (e.g., `momentum_roc_5d`, `zscore_20d`) |

### POST /api/v1/features/compute

Trigger statistical feature computation for specified symbols.

**Request Body:**
```json
{
  "symbols": ["AAPL", "MSFT", "NVDA"]
}
```

**Response:**
```json
{
  "status": "completed",
  "symbols": ["AAPL", "MSFT", "NVDA"],
  "message": "Computed 24 features for 3 symbols"
}
```

**Errors:**
- `400` - Empty symbols list
- `404` - None of the symbols found in database
- `500` - Computation failed

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/features/compute \
  -H "Content-Type: application/json" \
  -d '{"symbols": ["AAPL", "NVDA"]}'
```

---

## Error Handling

### Error Response Format

All errors follow a consistent JSON format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

For validation errors (422):
```json
{
  "detail": [
    {
      "loc": ["query", "limit"],
      "msg": "ensure this value is less than or equal to 100",
      "type": "value_error.number.not_le"
    }
  ]
}
```

### Error Codes

| HTTP Code | Name                 | Description                                          |
|-----------|----------------------|------------------------------------------------------|
| 400       | Bad Request          | Invalid parameters or request body                   |
| 404       | Not Found            | Resource not found (stock, insight, etc.)             |
| 422       | Validation Error     | Pydantic validation failed on request parameters     |
| 500       | Internal Server Error| Unexpected server error                              |

### Custom Application Errors

| Error Type        | HTTP Code | Description                                          |
|-------------------|-----------|------------------------------------------------------|
| `NotFoundError`   | 404       | Requested resource does not exist in the database    |
| `ValidationError` | 400       | Business logic validation failed                     |
| `DataSourceError` | 500       | External data source (Yahoo Finance, FRED) unavailable or returned an error |

### Common Error Scenarios

**Stock not found:**
```bash
curl http://localhost:8000/api/v1/stocks/INVALID
# 404: {"detail": "Stock INVALID not found"}
```

**Invalid pagination:**
```bash
curl "http://localhost:8000/api/v1/stocks?limit=500"
# 422: limit must be <= 100
```

**Data source failure:**
```bash
curl -X POST http://localhost:8000/api/v1/data/refresh -d '{"symbols": ["INVALID"]}'
# 200 with partial status and errors array:
# {"status": "failed", "symbols_updated": [], "errors": [{"symbol": "INVALID", "error": "..."}]}
```

**Analysis task not found:**
```bash
curl http://localhost:8000/api/v1/deep-insights/autonomous/status/nonexistent-id
# 404: {"detail": "Analysis task not found"}
```

**Modification on non-modifiable field:**
```bash
# POST /api/v1/insights/1/modifications with field_modified="id"
# 400: {"detail": "Field 'id' is not modifiable. Allowed fields: [...]"}
```

---

## Related Documentation

- **[README.md](README.md)** -- Project overview, quick start, and tech stack
- **[CLAUDE.md](CLAUDE.md)** -- Developer guidance: commands, architecture summary, key patterns
- **[ARCHITECTURE.md](ARCHITECTURE.md)** -- System architecture, analysis pipeline, data layer, concurrency model
- **[frontend/FRONTEND.md](frontend/FRONTEND.md)** -- Frontend components, hooks, state management, and styling
