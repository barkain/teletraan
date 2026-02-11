'use client';

import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  ReportListResponse,
  ReportDetail,
  PublishResponse,
} from '@/lib/types/report';

// Query keys for reports
export const reportKeys = {
  all: ['reports'] as const,
  lists: () => [...reportKeys.all, 'list'] as const,
  list: (params?: { limit?: number; offset?: number }) => [...reportKeys.lists(), params] as const,
  details: () => [...reportKeys.all, 'detail'] as const,
  detail: (id: string) => [...reportKeys.details(), id] as const,
};

// Empty response for placeholder data
const EMPTY_RESPONSE: ReportListResponse = { items: [], total: 0 };

/**
 * Custom hook for fetching the list of analysis reports
 */
export function useReportList(params?: { limit?: number; offset?: number }) {
  return useQuery<ReportListResponse>({
    queryKey: reportKeys.list(params),
    queryFn: () => api.reports.list(params),
    staleTime: 60 * 1000, // 1 minute
    gcTime: 10 * 60 * 1000, // 10 minutes cache
    placeholderData: keepPreviousData,
  });
}

/**
 * Custom hook for fetching a single report detail by ID
 */
export function useReportDetail(id: string | undefined) {
  return useQuery<ReportDetail>({
    queryKey: reportKeys.detail(id!),
    queryFn: () => api.reports.get(id!),
    enabled: !!id,
    staleTime: 60 * 1000, // 1 minute
    gcTime: 10 * 60 * 1000, // 10 minutes cache
  });
}

/**
 * Custom hook for publishing a report to GitHub Pages
 */
export function usePublishReport() {
  const queryClient = useQueryClient();

  return useMutation<PublishResponse, Error, string>({
    mutationFn: (id: string) => api.reports.publish(id),
    onSuccess: (_data, id) => {
      // Invalidate both the list and the specific detail to refresh published_url
      queryClient.invalidateQueries({ queryKey: reportKeys.lists() });
      queryClient.invalidateQueries({ queryKey: reportKeys.detail(id) });
    },
  });
}
