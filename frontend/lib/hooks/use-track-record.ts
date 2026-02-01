'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchApi } from '@/lib/api';
import type {
  TrackRecordStats,
  TrackRecordParams,
  OutcomeSummary,
  OutcomesListResponse,
  OutcomesListParams,
  InsightOutcome,
  MonthlyTrendResponse,
} from '@/lib/types/track-record';

// Query keys for track record
export const trackRecordKeys = {
  all: ['track-record'] as const,
  stats: (params?: TrackRecordParams) => [...trackRecordKeys.all, 'stats', params] as const,
  outcomes: () => [...trackRecordKeys.all, 'outcomes'] as const,
  outcomesSummary: (params?: TrackRecordParams) => [...trackRecordKeys.outcomes(), 'summary', params] as const,
  outcomesList: (params?: OutcomesListParams) => [...trackRecordKeys.outcomes(), 'list', params] as const,
  outcomeDetail: (insightId: string) => [...trackRecordKeys.outcomes(), 'detail', insightId] as const,
};

/**
 * Fetch track record statistics from knowledge API
 */
export function useTrackRecord(params?: TrackRecordParams) {
  return useQuery<TrackRecordStats>({
    queryKey: trackRecordKeys.stats(params),
    queryFn: async () => {
      const response = await fetchApi<TrackRecordStats>('/api/v1/knowledge/track-record', {
        params: params as Record<string, string | number | boolean | undefined>,
      });
      return response;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Fetch outcome summary statistics
 */
export function useOutcomeSummary(params?: TrackRecordParams) {
  return useQuery<OutcomeSummary>({
    queryKey: trackRecordKeys.outcomesSummary(params),
    queryFn: async () => {
      const queryParams: Record<string, string | number | boolean | undefined> = {};
      if (params?.insight_type) queryParams.insight_type = params.insight_type;
      if (params?.action_type) queryParams.action_type = params.action_type;
      if (params?.lookback_days) queryParams.lookback_days = params.lookback_days;

      const response = await fetchApi<OutcomeSummary>('/api/v1/outcomes/summary', {
        params: queryParams,
      });
      return response;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Fetch list of insight outcomes
 */
export function useOutcomes(params?: OutcomesListParams) {
  return useQuery<OutcomesListResponse>({
    queryKey: trackRecordKeys.outcomesList(params),
    queryFn: async () => {
      const response = await fetchApi<OutcomesListResponse>('/api/v1/outcomes', {
        params: params as Record<string, string | number | boolean | undefined>,
      });
      return response;
    },
    staleTime: 2 * 60 * 1000, // 2 minutes
  });
}

/**
 * Fetch outcome for a specific insight
 */
export function useInsightOutcome(insightId: string | undefined) {
  return useQuery<InsightOutcome | null>({
    queryKey: trackRecordKeys.outcomeDetail(insightId!),
    queryFn: async () => {
      try {
        const response = await fetchApi<InsightOutcome>(`/api/v1/outcomes/insight/${insightId}`);
        return response;
      } catch (error) {
        // Return null if no outcome exists for this insight
        if (error instanceof Error && error.message.includes('404')) {
          return null;
        }
        throw error;
      }
    },
    enabled: !!insightId,
    staleTime: 2 * 60 * 1000, // 2 minutes
  });
}

/**
 * Fetch monthly trend data for success rate over time
 */
export function useMonthlyTrend(params?: { lookback_months?: number }) {
  return useQuery<MonthlyTrendResponse>({
    queryKey: [...trackRecordKeys.all, 'monthly-trend', params],
    queryFn: async () => {
      const response = await fetchApi<MonthlyTrendResponse>('/api/v1/knowledge/track-record/monthly-trend', {
        params: params as Record<string, string | number | boolean | undefined>,
      });
      return response;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}
