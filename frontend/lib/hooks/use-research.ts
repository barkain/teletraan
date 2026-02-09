'use client';

import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type {
  FollowUpResearch,
  ResearchListResponse,
  ResearchListParams,
  ResearchCreateRequest,
} from '@/lib/types/research';

// Query keys for research
export const researchKeys = {
  all: ['research'] as const,
  lists: () => [...researchKeys.all, 'list'] as const,
  list: (params?: ResearchListParams) => [...researchKeys.lists(), params] as const,
  details: () => [...researchKeys.all, 'detail'] as const,
  detail: (id: number) => [...researchKeys.details(), id] as const,
};

// Empty response for placeholder data
const EMPTY_RESPONSE: ResearchListResponse = { items: [], total: 0 };

/**
 * Custom hook for fetching research list with optional filtering
 */
export function useResearchList(params?: ResearchListParams) {
  return useQuery<ResearchListResponse>({
    queryKey: researchKeys.list(params),
    queryFn: () => api.research.list(params),
    staleTime: 30 * 1000, // 30 seconds - research status can change
    gcTime: 10 * 60 * 1000, // 10 minutes cache
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      // Auto-refetch if any items are running/pending
      const data = query.state.data as ResearchListResponse | undefined;
      const hasActive = data?.items?.some(
        (item) => item.status === 'RUNNING' || item.status === 'PENDING'
      );
      return hasActive ? 5000 : false; // Poll every 5s if active research exists
    },
  });
}

/**
 * Custom hook for fetching a single research detail by ID
 */
export function useResearchDetail(id: number | undefined) {
  return useQuery<FollowUpResearch>({
    queryKey: researchKeys.detail(id!),
    queryFn: () => api.research.get(id!),
    enabled: !!id,
    staleTime: 15 * 1000, // 15 seconds
    gcTime: 10 * 60 * 1000,
    refetchInterval: (query) => {
      const data = query.state.data as FollowUpResearch | undefined;
      if (data?.status === 'RUNNING' || data?.status === 'PENDING') {
        return 3000; // Poll every 3s for active research
      }
      return false;
    },
  });
}

/**
 * Custom hook for triggering a new research request
 */
export function useTriggerResearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: ResearchCreateRequest) => api.research.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.lists() });
    },
  });
}

/**
 * Custom hook for cancelling a research request
 */
export function useCancelResearch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => api.research.cancel(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: researchKeys.all });
    },
  });
}
