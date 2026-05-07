'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { AlphaTaskStatus, AlphaRunDetail } from '@/lib/api';

export const alphaKeys = {
  all: ['alpha-engine'] as const,
  active: () => [...alphaKeys.all, 'active'] as const,
  status: (taskId: string) => [...alphaKeys.all, 'status', taskId] as const,
  runs: (params?: Record<string, unknown>) => [...alphaKeys.all, 'runs', params ?? {}] as const,
  run: (runId: string) => [...alphaKeys.all, 'run', runId] as const,
};

function isTerminal(status: string) {
  return status === 'completed' || status === 'failed' || status === 'cancelled';
}

export function useAlphaActive() {
  return useQuery<AlphaTaskStatus | null>({
    queryKey: alphaKeys.active(),
    queryFn: () => api.alphaEngine.active(),
    staleTime: 5 * 1000,
  });
}

export function useAlphaStatus(taskId: string | null) {
  return useQuery<AlphaTaskStatus>({
    queryKey: alphaKeys.status(taskId!),
    queryFn: () => api.alphaEngine.status(taskId!),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || isTerminal(data.status)) return false;
      return 2000;
    },
    refetchIntervalInBackground: true,
  });
}

export function useAlphaRuns(params?: { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: alphaKeys.runs(params),
    queryFn: () => api.alphaEngine.runs(params),
    staleTime: 30 * 1000,
  });
}

export function useAlphaRun(runId: string | null) {
  return useQuery<AlphaRunDetail>({
    queryKey: alphaKeys.run(runId!),
    queryFn: () => api.alphaEngine.run(runId!),
    enabled: !!runId,
    staleTime: 60 * 1000,
  });
}

export function useStartAlphaRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.alphaEngine.start(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: alphaKeys.all });
    },
  });
}
