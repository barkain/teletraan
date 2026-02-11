// Get the base URL, removing any trailing /api/v1 if present (to avoid duplication)
const rawUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_URL = rawUrl.replace(/\/api\/v1\/?$/, '');

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

// Generic fetch function with query params support
export async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit & { params?: Record<string, string | number | boolean | undefined> }
): Promise<T> {
  let url = `${API_URL}${endpoint}`;

  // Add query params if provided
  if (options?.params) {
    const params = new URLSearchParams();
    Object.entries(options.params).forEach(([key, value]) => {
      if (value !== undefined) {
        params.set(key, String(value));
      }
    });
    const queryString = params.toString();
    if (queryString) {
      url += `?${queryString}`;
    }
  }

  const { params: _, ...fetchOptions } = options || {};

  const res = await fetch(url, {
    ...fetchOptions,
    headers: {
      'Content-Type': 'application/json',
      ...fetchOptions?.headers,
    },
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new ApiError(res.status, errorBody || res.statusText);
  }

  return res.json();
}

// POST helper
export async function postApi<T>(endpoint: string, body?: unknown): Promise<T> {
  return fetchApi<T>(endpoint, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
}

// PUT helper
export async function putApi<T>(endpoint: string, body?: unknown): Promise<T> {
  return fetchApi<T>(endpoint, {
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  });
}

// DELETE helper
export async function deleteApi<T>(endpoint: string): Promise<T> {
  return fetchApi<T>(endpoint, {
    method: 'DELETE',
  });
}

// ============================================
// API v1 Endpoints - Complete API Client
// ============================================

// Health Check Response
export interface HealthResponse {
  status: string;
  timestamp: string;
  version: string;
}

// Stock List Params
export interface StockListParams {
  sector?: string;
  limit?: number;
  offset?: number;
}

// Stock List Response
export interface StockListResponse {
  items: Stock[];
  total: number;
}

// Stock Response
export interface StockResponse extends Stock {
  description?: string;
  employees?: number;
  headquarters?: string;
  website?: string;
}

// History Params
export interface HistoryParams {
  days?: number;
  interval?: 'daily' | 'weekly' | 'monthly';
}

// Insight List Params
export interface InsightListParams {
  type?: string;
  severity?: string;
  symbol?: string;
  search?: string;
  start_date?: string;
  end_date?: string;
  page?: number;
  per_page?: number;
}

// Insight List Response
export type InsightListResponse = PaginatedResponse<Insight>;

// Insight Response
export type InsightResponse = Insight;

// Technical Analysis Response
export interface TechnicalAnalysisResponse {
  symbol: string;
  price: number;
  change: number;
  change_percent: number;
  indicators: {
    rsi: number;
    macd: {
      value: number;
      signal: number;
      histogram: number;
    };
    moving_averages: {
      sma_20: number;
      sma_50: number;
      sma_200: number;
      ema_12: number;
      ema_26: number;
    };
  };
  support_resistance: {
    support: number[];
    resistance: number[];
  };
  recommendation: 'strong_buy' | 'buy' | 'hold' | 'sell' | 'strong_sell';
  analysis_date: string;
}

// Sector Analysis Response
export interface SectorAnalysisResponse {
  sectors: Array<{
    symbol: string;
    name: string;
    performance: number;
    weekly_performance: number;
    monthly_performance: number;
    volume: number;
    market_cap?: number;
  }>;
  rotation_phase: string;
  historical_performance: Array<{
    date: string;
    [sectorSymbol: string]: number | string;
  }>;
  last_updated: string;
}

// Search Response
export interface SearchResponse {
  stocks: Array<Stock & { relevance_score: number }>;
  insights: Array<Insight & { relevance_score: number }>;
  total: number;
  query: string;
}

// Settings Response (properly typed)
export interface SettingsResponseV1 {
  settings: {
    watchlist_symbols?: string[];
    refresh_interval?: number;
    theme?: string;
    chart_type?: string;
    notification_preferences?: {
      price_alerts: boolean;
      insight_alerts: boolean;
      daily_summary: boolean;
    };
    api_key?: string | null;
  };
}

// Export Params
export interface ExportParams {
  format?: 'csv' | 'json' | 'xlsx';
  start_date?: string;
  end_date?: string;
}

// Deep Insight List Params
export interface DeepInsightListParams {
  insight_type?: DeepInsightType;
  action?: InsightAction;
  symbol?: string;
  min_confidence?: number;
  start_date?: string;
  end_date?: string;
  limit?: number;
  offset?: number;
}

// ============================================
// Complete API Client Object
// ============================================

export const api = {
  // Health
  health: () => fetchApi<HealthResponse>('/api/v1/health'),

  // Stocks
  stocks: {
    list: async (params?: StockListParams): Promise<StockListResponse> => {
      // The API returns { stocks: [...] } but we need { items: [...], total: number }
      const response = await fetchApi<{ stocks: Stock[] }>('/api/v1/stocks', {
        params: params as Record<string, string | number | boolean | undefined>
      });
      return {
        items: response.stocks || [],
        total: response.stocks?.length || 0,
      };
    },
    get: (symbol: string) =>
      fetchApi<StockResponse>(`/api/v1/stocks/${symbol}`),
    history: (symbol: string, params?: HistoryParams) =>
      fetchApi<PriceHistory[]>(`/api/v1/stocks/${symbol}/history`, { params: params as Record<string, string | number | boolean | undefined> }),
  },

  // Insights
  insights: {
    list: async (params?: InsightListParams): Promise<InsightListResponse> => {
      // The API returns { insights: [], total: 0 } but we need { items: [], total, page, per_page, total_pages }
      const response = await fetchApi<{ insights: Insight[]; total: number }>('/api/v1/insights', {
        params: params as Record<string, string | number | boolean | undefined>
      });
      const page = params?.page || 1;
      const perPage = params?.per_page || 12;
      return {
        items: response.insights || [],
        total: response.total || 0,
        page,
        per_page: perPage,
        total_pages: Math.ceil((response.total || 0) / perPage),
      };
    },
    get: (id: number | string) =>
      fetchApi<InsightResponse>(`/api/v1/insights/${id}`),
    addAnnotation: (id: number | string, note: string) =>
      postApi<InsightAnnotation>(`/api/v1/insights/${id}/annotations`, { note }),
  },

  // Deep Insights
  deepInsights: {
    list: async (params?: DeepInsightListParams): Promise<DeepInsightListResponse> => {
      const response = await fetchApi<{ items: DeepInsight[]; total: number }>('/api/v1/deep-insights', {
        params: params as Record<string, string | number | boolean | undefined>
      });
      return {
        items: response.items || [],
        total: response.total || 0,
      };
    },
    get: (id: number) =>
      fetchApi<DeepInsight>(`/api/v1/deep-insights/${id}`),
    bySymbol: (symbol: string, params?: Omit<DeepInsightListParams, 'symbol'>) =>
      fetchApi<DeepInsightListResponse>(`/api/v1/deep-insights/symbol/${symbol}`, {
        params: params as Record<string, string | number | boolean | undefined>
      }),
    byType: (insightType: DeepInsightType, params?: Omit<DeepInsightListParams, 'insight_type'>) =>
      fetchApi<DeepInsightListResponse>(`/api/v1/deep-insights/type/${insightType}`, {
        params: params as Record<string, string | number | boolean | undefined>
      }),
    generate: (symbols?: string[]) =>
      postApi<{ message: string; job_id?: string }>('/api/v1/deep-insights/generate', { symbols }),
    // Autonomous analysis - no symbols required
    autonomous: (params?: { max_insights?: number; deep_dive_count?: number }) =>
      postApi<AutonomousAnalysisResponse>('/api/v1/deep-insights/autonomous', params),
  },

  // Analysis
  analysis: {
    technical: (symbol: string) =>
      fetchApi<TechnicalAnalysisResponse>(`/api/v1/analysis/technical/${symbol}`),
    sectors: () =>
      fetchApi<SectorAnalysisResponse>('/api/v1/analysis/sectors'),
    run: (symbols?: string[]) =>
      postApi<{ message: string; job_id?: string }>('/api/v1/analysis/run', { symbols }),
  },

  // Search
  search: (q: string) =>
    fetchApi<SearchResponse>(`/api/v1/search`, { params: { q } }),

  // Export
  export: {
    stocks: (params?: ExportParams) =>
      fetchApi<Blob>('/api/v1/export/stocks', { params: params as Record<string, string | number | boolean | undefined> }),
    insights: (params?: ExportParams) =>
      fetchApi<Blob>('/api/v1/export/insights', { params: params as Record<string, string | number | boolean | undefined> }),
    portfolio: (params?: ExportParams) =>
      fetchApi<Blob>('/api/v1/export/portfolio', { params: params as Record<string, string | number | boolean | undefined> }),
  },

  // Settings
  settings: {
    get: () =>
      fetchApi<SettingsResponseV1>('/api/v1/settings'),
    update: (key: string, value: unknown) =>
      putApi<{ message: string }>(`/api/v1/settings/${key}`, { value }),
    watchlist: {
      get: () =>
        fetchApi<WatchlistSettings>('/api/v1/settings/watchlist'),
      update: (symbols: string[]) =>
        putApi<WatchlistSettings>('/api/v1/settings/watchlist', { symbols }),
    },
  },

  // Portfolio
  portfolio: {
    get: () =>
      fetchApi<Portfolio>('/api/v1/portfolio'),
    create: (data?: { name?: string; description?: string }) =>
      postApi<Portfolio>('/api/v1/portfolio', data),
    addHolding: (holding: HoldingCreate) =>
      postApi<PortfolioHolding>('/api/v1/portfolio/holdings', holding),
    updateHolding: (holdingId: number, data: HoldingUpdate) =>
      putApi<PortfolioHolding>(`/api/v1/portfolio/holdings/${holdingId}`, data),
    deleteHolding: (holdingId: number) =>
      deleteApi<void>(`/api/v1/portfolio/holdings/${holdingId}`),
    impact: () =>
      fetchApi<PortfolioImpact>('/api/v1/portfolio/impact'),
  },

  // Research
  research: {
    list: (params?: ResearchListParams) =>
      fetchApi<ResearchListResponse>('/api/v1/research', {
        params: params as Record<string, string | number | boolean | undefined>,
      }),
    get: (id: number) =>
      fetchApi<FollowUpResearch>(`/api/v1/research/${id}`),
    create: (data: ResearchCreateRequest) =>
      postApi<FollowUpResearch>('/api/v1/research', data),
    cancel: (id: number) =>
      deleteApi<void>(`/api/v1/research/${id}`),
  },

  // Reports
  reports: {
    list: (params?: { limit?: number; offset?: number }) =>
      fetchApi<ReportListResponse>('/api/v1/reports', {
        params: params as Record<string, string | number | boolean | undefined>,
      }),
    get: (id: string) =>
      fetchApi<ReportDetail>(`/api/v1/reports/${id}`),
    htmlUrl: (id: string) => `${API_URL}/api/v1/reports/${id}/html`,
    publish: (id: string) =>
      postApi<PublishResponse>(`/api/v1/reports/${id}/publish`),
  },
};

// ============================================
// Legacy API endpoints (for backwards compatibility)
// ============================================

// Stock endpoints (legacy - uses v1 under the hood)
export const stocksApi = {
  list: () => api.stocks.list().then(r => r.items),
  get: (symbol: string) => api.stocks.get(symbol),
  getPriceHistory: (symbol: string, days?: number) =>
    api.stocks.history(symbol, { days }),
};

// Insights endpoints (legacy)
export const insightsApi = {
  list: (filters?: InsightFilters) => {
    const params: InsightListParams = {};
    if (filters?.type && filters.type !== 'all') params.type = filters.type;
    if (filters?.severity && filters.severity !== 'all') params.severity = filters.severity;
    if (filters?.search) params.search = filters.search;
    if (filters?.startDate) params.start_date = filters.startDate;
    if (filters?.endDate) params.end_date = filters.endDate;
    if (filters?.page) params.page = filters.page;
    if (filters?.perPage) params.per_page = filters.perPage;
    return api.insights.list(params);
  },
  get: (id: string) => api.insights.get(id),
  generate: (symbol: string) =>
    postApi<Insight>('/api/v1/insights/generate', { symbol }),
  // Annotation endpoints
  getAnnotations: (insightId: string) =>
    fetchApi<InsightAnnotation[]>(`/api/v1/insights/${insightId}/annotations`),
  addAnnotation: (insightId: string, note: string) =>
    api.insights.addAnnotation(insightId, note),
  updateAnnotation: (insightId: string, annotationId: number, note: string) =>
    putApi<InsightAnnotation>(`/api/v1/insights/${insightId}/annotations/${annotationId}`, { note }),
  deleteAnnotation: (insightId: string, annotationId: number) =>
    deleteApi<{ message: string }>(`/api/v1/insights/${insightId}/annotations/${annotationId}`),
};

// Analysis endpoints (legacy)
export const analysisApi = {
  analyze: (symbol: string, prompt?: string) =>
    postApi<AnalysisResult>('/api/v1/analysis', { symbol, prompt }),
  technical: (symbol: string) => api.analysis.technical(symbol),
  sectors: () => api.analysis.sectors(),
};

// Chat endpoints (legacy)
export const chatApi = {
  send: (message: string, context?: { symbol?: string }) =>
    postApi<{ response: string }>('/api/v1/chat', { message, ...context }),
};

// Import types
import type { Stock, PriceHistory, Insight, InsightAnnotation, InsightFilters, AnalysisResult, PaginatedResponse, RefreshDataResponse, WatchlistSettings, DeepInsight, DeepInsightListResponse, DeepInsightType, InsightAction, AutonomousAnalysisResponse, Portfolio, PortfolioHolding, HoldingCreate, HoldingUpdate, PortfolioImpact } from '@/types';
import type { KnowledgePattern, KnowledgePatternsResponse, KnowledgePatternsParams, MatchingPatternsParams, ConversationTheme, ConversationThemesResponse, ConversationThemesParams } from '@/lib/types/knowledge';
import type { FollowUpResearch, ResearchListResponse, ResearchListParams, ResearchCreateRequest } from '@/lib/types/research';
import type { ReportListResponse, ReportDetail, PublishResponse } from '@/lib/types/report';

// ============================================
// Data Refresh API
// ============================================

/**
 * Refresh market data for specified symbols or all tracked symbols
 * @param symbols Optional array of stock symbols to refresh. If not provided, refreshes all.
 * @returns RefreshDataResponse with status, updated symbols, and records added
 */
export async function refreshData(symbols?: string[]): Promise<RefreshDataResponse> {
  return postApi<RefreshDataResponse>('/api/v1/data/refresh', { symbols });
}

// ============================================
// Knowledge API
// ============================================

export const knowledgeApi = {
  // Patterns
  patterns: {
    list: async (params?: KnowledgePatternsParams): Promise<KnowledgePatternsResponse> => {
      return fetchApi<KnowledgePatternsResponse>('/api/v1/knowledge/patterns', {
        params: params as Record<string, string | number | boolean | undefined>
      });
    },
    get: (id: string) =>
      fetchApi<KnowledgePattern>(`/api/v1/knowledge/patterns/${id}`),
    matching: async (params?: MatchingPatternsParams): Promise<KnowledgePatternsResponse> => {
      const queryParams: Record<string, string | number | boolean | undefined> = {};
      if (params?.symbols) {
        queryParams.symbols = params.symbols.join(',');
      }
      if (params?.current_rsi !== undefined) {
        queryParams.current_rsi = params.current_rsi;
      }
      if (params?.current_vix !== undefined) {
        queryParams.current_vix = params.current_vix;
      }
      return fetchApi<KnowledgePatternsResponse>('/api/v1/knowledge/patterns/matching', {
        params: queryParams
      });
    },
  },

  // Themes
  themes: {
    list: async (params?: ConversationThemesParams): Promise<ConversationThemesResponse> => {
      return fetchApi<ConversationThemesResponse>('/api/v1/knowledge/themes', {
        params: params as Record<string, string | number | boolean | undefined>
      });
    },
    get: (id: string) =>
      fetchApi<ConversationTheme>(`/api/v1/knowledge/themes/${id}`),
  },
};
