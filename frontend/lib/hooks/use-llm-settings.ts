'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { LLMProviderStatus, LLMProviderConfig, LLMTestResult } from '@/types';

export const llmSettingsKeys = {
  all: ['llm-settings'] as const,
};

export function useLLMSettings() {
  return useQuery<LLMProviderStatus>({
    queryKey: llmSettingsKeys.all,
    queryFn: () => api.settings.llm.get(),
    staleTime: 60 * 1000,
  });
}

export function useUpdateLLMSettings() {
  const queryClient = useQueryClient();

  return useMutation<LLMProviderStatus, Error, LLMProviderConfig>({
    mutationFn: (config) => api.settings.llm.update(config),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: llmSettingsKeys.all });
    },
  });
}

export function useTestLLMConnection() {
  return useMutation<LLMTestResult, Error>({
    mutationFn: () => api.settings.llm.test(),
  });
}
