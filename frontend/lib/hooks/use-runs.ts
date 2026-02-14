'use client';

import { useQuery } from '@tanstack/react-query';
import { runsApi } from '@/lib/api';
import type { RunListResponse, RunsAggregateStats, RunSummary } from '@/types';

// Query key factory for runs
export const runKeys = {
  all: ['runs'] as const,
  lists: () => [...runKeys.all, 'list'] as const,
  list: (params: Record<string, unknown>) => [...runKeys.lists(), params] as const,
  stats: () => [...runKeys.all, 'stats'] as const,
  details: () => [...runKeys.all, 'detail'] as const,
  detail: (id: string) => [...runKeys.details(), id] as const,
};

// Fetch paginated list of runs
export function useRuns(params?: { page?: number; page_size?: number; status?: string; search?: string }) {
  return useQuery<RunListResponse>({
    queryKey: runKeys.list(params ?? {}),
    queryFn: () => runsApi.list(params),
    staleTime: 60 * 1000, // 1 minute
  });
}

// Fetch aggregate stats across all runs
export function useRunsStats() {
  return useQuery<RunsAggregateStats>({
    queryKey: runKeys.stats(),
    queryFn: () => runsApi.stats(),
    staleTime: 60 * 1000, // 1 minute
  });
}

// Fetch a single run by ID
export function useRun(id: string | undefined) {
  return useQuery<RunSummary>({
    queryKey: runKeys.detail(id!),
    queryFn: () => runsApi.get(id!),
    enabled: !!id,
    staleTime: 60 * 1000, // 1 minute
  });
}
