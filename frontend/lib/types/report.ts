/**
 * Report Types
 * Types for analysis report endpoints
 */

export interface ReportSummary {
  id: string;
  started_at: string | null;
  completed_at: string | null;
  elapsed_seconds: number | null;
  market_regime: string | null;
  top_sectors: string[];
  discovery_summary: string | null;
  insights_count: number;
  published_url: string | null;
  symbols: string[];
  action_summary: Record<string, number>;
  avg_confidence: number;
  insight_types: string[];
}

export interface ReportInsight {
  id: number;
  insight_type: string | null;
  action: string | null;
  title: string;
  thesis: string | null;
  primary_symbol: string | null;
  related_symbols: string[];
  confidence: number | null;
  time_horizon: string | null;
  risk_factors: string[];
  entry_zone: string | null;
  target_price: string | null;
  stop_loss: string | null;
  invalidation_trigger: string | null;
  created_at: string | null;
}

export interface ReportDetail extends ReportSummary {
  insights: ReportInsight[];
  phases_completed: string[];
}

export interface ReportListResponse {
  items: ReportSummary[];
  total: number;
}

export interface PublishResponse {
  published_url: string;
  message: string;
}
