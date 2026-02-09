/**
 * Research Types
 * Types for follow-up research requests spawned from conversations
 */

// Research type categories
export type ResearchType =
  | 'SCENARIO_ANALYSIS'
  | 'DEEP_DIVE'
  | 'CORRELATION_CHECK'
  | 'WHAT_IF'
  | 'SECTOR_DEEP_DIVE'
  | 'TECHNICAL_FOCUS'
  | 'MACRO_IMPACT';

// Research execution status
export type ResearchStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

// Follow-up research record
export interface FollowUpResearch {
  id: number;
  conversation_id: number | null;
  source_message_id: number | null;
  research_type: ResearchType;
  query: string;
  parameters: Record<string, unknown>;
  status: ResearchStatus;
  result_insight_id: number | null;
  error_message: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string | null;
  parent_insight_summary?: string;
  result_insight_summary?: string;
}

// Response type for research list endpoint
export interface ResearchListResponse {
  items: FollowUpResearch[];
  total: number;
}

// Request parameters for filtering research
export interface ResearchListParams {
  limit?: number;
  offset?: number;
  status?: ResearchStatus;
  research_type?: ResearchType;
}

// Request body for creating a new research
export interface ResearchCreateRequest {
  parent_insight_id?: number;
  research_type: ResearchType;
  query: string;
  symbols?: string[];
  questions?: string[];
}
