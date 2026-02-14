'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import type { LLMProviderStatus, LLMProviderConfig, LLMTestRequest, LLMTestResult } from '@/types';

/** Default status returned when no LLM settings have been saved yet. */
const DEFAULT_LLM_STATUS: LLMProviderStatus = {
  active_provider: 'subscription',
  active_provider_display: 'Unknown',
  configured_provider: 'auto',
  model: 'claude-sonnet-4-20250514',
  env_override: false,
  anthropic_api_key: null,
  anthropic_auth_token: null,
  anthropic_base_url: null,
  api_timeout_ms: null,
  aws_region: null,
  vertex_project: null,
  vertex_region: null,
};

export const llmSettingsKeys = {
  all: ['llm-settings'] as const,
};

export function useLLMSettings() {
  return useQuery<LLMProviderStatus>({
    queryKey: llmSettingsKeys.all,
    queryFn: async () => {
      try {
        return await api.settings.llm.get();
      } catch (err) {
        // Treat 404 as "no settings saved yet" and return defaults
        if (err instanceof ApiError && err.status === 404) {
          return DEFAULT_LLM_STATUS;
        }
        throw err;
      }
    },
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

export function useResetLLMSettings() {
  const queryClient = useQueryClient();

  return useMutation<{ status: string; message: string }, Error, void>({
    mutationFn: () => api.settings.llm.reset(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: llmSettingsKeys.all });
    },
  });
}

export function useTestLLMConnection() {
  return useMutation<LLMTestResult, Error, LLMTestRequest>({
    mutationFn: (body) => api.settings.llm.test(body),
  });
}
