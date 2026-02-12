'use client';

import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { DeepInsight, DeepInsightListResponse, DeepInsightType, InsightAction } from '@/types';

// Query keys for deep insights
export const deepInsightKeys = {
  all: ['deep-insights'] as const,
  lists: () => [...deepInsightKeys.all, 'list'] as const,
  list: (params?: DeepInsightParams) => [...deepInsightKeys.lists(), params] as const,
  details: () => [...deepInsightKeys.all, 'detail'] as const,
  detail: (id: number) => [...deepInsightKeys.details(), id] as const,
  recent: (limit: number) => [...deepInsightKeys.all, 'recent', limit] as const,
};

// Parameters for listing deep insights
export interface DeepInsightParams {
  limit?: number;
  offset?: number;
  action?: InsightAction;
  insight_type?: DeepInsightType;
  symbol?: string;
}

/**
 * Custom hook for fetching deep insights list with optional filtering
 */
export function useDeepInsights(params?: DeepInsightParams) {
  return useQuery<DeepInsightListResponse>({
    queryKey: deepInsightKeys.list(params),
    queryFn: () => api.deepInsights.list(params),
    staleTime: 60 * 1000, // 1 minute
    gcTime: 10 * 60 * 1000, // 10 minutes cache
    placeholderData: keepPreviousData,
  });
}

/**
 * Custom hook for fetching a single deep insight by ID
 */
export function useDeepInsight(id: number | undefined) {
  return useQuery<DeepInsight>({
    queryKey: deepInsightKeys.detail(id!),
    queryFn: () => api.deepInsights.get(id!),
    enabled: !!id,
    staleTime: 60 * 1000, // 1 minute
    gcTime: 10 * 60 * 1000, // 10 minutes cache
  });
}

/**
 * Custom hook for fetching recent deep insights for dashboard display.
 * Optimized for fast initial load with stale-while-revalidate pattern.
 */
export function useRecentDeepInsights(limit: number = 9) {
  return useQuery<DeepInsightListResponse>({
    queryKey: deepInsightKeys.recent(limit),
    queryFn: () => api.deepInsights.list({ limit }),
    staleTime: 30 * 1000, // 30 seconds - refresh more frequently on dashboard
    gcTime: 10 * 60 * 1000, // 10 minutes cache for stale-while-revalidate
    refetchOnMount: 'always', // Always check for fresh data when visiting dashboard
  });
}
