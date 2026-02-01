// Stock types
export interface Stock {
  symbol: string;
  name: string;
  sector?: string;
  current_price?: number;
  change_percent?: number;
  market_cap?: number;
  volume?: number;
  created_at?: string;
  updated_at?: string;
}

// Price history for charts
export interface PriceHistory {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// Insight types and severity levels
export type InsightType = 'pattern' | 'anomaly' | 'sector' | 'technical' | 'economic';
export type InsightSeverity = 'info' | 'warning' | 'alert';

// LLM-generated insights
export interface Insight {
  id: string;
  symbol?: string;
  type: InsightType;
  severity: InsightSeverity;
  title: string;
  content: string;
  description?: string;
  summary?: string;
  confidence?: number;
  created_at: string;
  metadata?: Record<string, unknown>;
  annotations?: InsightAnnotation[];
}

// Insight annotation
export interface InsightAnnotation {
  id: number;
  insight_id: number;
  note: string;
  created_at: string;
  updated_at?: string;
}

// Insight filters
export interface InsightFilters {
  type?: InsightType | 'all';
  severity?: InsightSeverity | 'all';
  search?: string;
  startDate?: string;
  endDate?: string;
  page?: number;
  perPage?: number;
}

// Analysis result from LLM
export interface AnalysisResult {
  symbol: string;
  analysis: string;
  sentiment: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  key_points: string[];
  risks: string[];
  opportunities: string[];
  created_at: string;
}

// Chat message
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  context?: {
    symbol?: string;
    insight_id?: string;
  };
}

// API response wrapper
export interface ApiResponse<T> {
  data: T;
  message?: string;
  error?: string;
}

// Pagination
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

// Settings types
export interface NotificationPreferences {
  price_alerts: boolean;
  insight_alerts: boolean;
  daily_summary: boolean;
}

export interface UserSettings {
  watchlist_symbols: string[];
  refresh_interval: 1 | 5 | 15 | 30;
  theme: 'light' | 'dark' | 'system';
  chart_type: 'candlestick' | 'line' | 'area';
  notification_preferences: NotificationPreferences;
  api_key: string | null;
}

export interface SettingsResponse {
  settings: UserSettings;
}

export interface SettingUpdateRequest {
  value: unknown;
}

// Data refresh response
export interface RefreshDataResponse {
  status: string;
  symbols_updated: string[];
  records_added: number;
}

// Watchlist settings
export interface WatchlistSettings {
  symbols: string[];
  last_refresh: string | null;
}

// ============================================
// Deep Insights Types
// ============================================

export type InsightAction = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL' | 'WATCH';

export type DeepInsightType = 'opportunity' | 'risk' | 'rotation' | 'macro' | 'divergence' | 'correlation';

export interface AnalystEvidence {
  analyst: string;
  finding: string;
  confidence?: number;
}

export interface DiscoveryContext {
  macro_regime: string;
  macro_themes: string[];
  top_sectors: string[];
  opportunity_type: string;
}

export interface DeepInsight {
  id: number;
  created_at: string;
  updated_at?: string;

  // Classification
  insight_type: DeepInsightType;
  action: InsightAction;

  // Content
  title: string;
  thesis: string;

  // Symbols
  primary_symbol?: string;
  related_symbols: string[];

  // Evidence
  supporting_evidence: AnalystEvidence[];

  // Confidence & Timing
  confidence: number;
  time_horizon: string;

  // Risk Management
  risk_factors: string[];
  invalidation_trigger?: string;

  // Historical context
  historical_precedent?: string;

  // Metadata
  analysts_involved: string[];
  data_sources: string[];

  // Trading parameters (autonomous discovery)
  entry_zone?: string;
  target_price?: string;
  stop_loss?: string;
  timeframe?: 'swing' | 'position' | 'long-term';
  discovery_context?: DiscoveryContext;

  // Parent insight linking (for follow-up insights derived from conversations)
  parent_insight_id?: number;
  source_conversation_id?: number;
}

export interface DeepInsightListResponse {
  items: DeepInsight[];
  total: number;
}

// Autonomous Analysis Response
export interface AutonomousAnalysisResponse {
  analysis_id: string;
  status: string;
  insights_count: number;
  elapsed_seconds: number;
  discovery_summary: string;
  market_regime: string;
  top_sectors: string[];
  phases_completed?: string[];
  errors?: string[];
}

// Background Analysis Task
export interface AnalysisTask {
  id: string;
  status: string;
  progress: number;
  current_phase: string | null;
  phase_details: string | null;
  phase_name: string | null;
  result_insight_ids: number[] | null;
  result_analysis_id: string | null;
  market_regime: string | null;
  top_sectors: string[] | null;
  discovery_summary: string | null;
  phases_completed: string[] | null;
  error_message: string | null;
  elapsed_seconds: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface StartAnalysisResponse {
  task_id: string;
  status: string;
  message: string;
}
