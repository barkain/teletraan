'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { insightsApi } from '@/lib/api';
import type { Insight, InsightFilters, InsightAnnotation, PaginatedResponse } from '@/types';

// Query keys for insights
export const insightKeys = {
  all: ['insights'] as const,
  lists: () => [...insightKeys.all, 'list'] as const,
  list: (filters: InsightFilters) => [...insightKeys.lists(), filters] as const,
  details: () => [...insightKeys.all, 'detail'] as const,
  detail: (id: string) => [...insightKeys.details(), id] as const,
};

// Query keys for annotations
export const annotationKeys = {
  all: (insightId: string | number) => ['insight-annotations', String(insightId)] as const,
};

// Custom hook for fetching insights list with filters
export function useInsights(filters: InsightFilters = {}) {
  return useQuery<PaginatedResponse<Insight>>({
    queryKey: insightKeys.list(filters),
    queryFn: () => insightsApi.list(filters),
    staleTime: 60 * 1000, // 1 minute
  });
}

// Custom hook for fetching a single insight
export function useInsight(id: string | undefined) {
  return useQuery<Insight>({
    queryKey: insightKeys.detail(id!),
    queryFn: () => insightsApi.get(id!),
    enabled: !!id,
    staleTime: 60 * 1000, // 1 minute
  });
}

// Custom hook for fetching annotations for a specific insight
export function useInsightAnnotations(insightId: string | number | undefined) {
  return useQuery<InsightAnnotation[]>({
    queryKey: annotationKeys.all(insightId!),
    queryFn: () => insightsApi.getAnnotations(String(insightId)),
    enabled: !!insightId,
    staleTime: 30 * 1000, // 30 seconds
  });
}

// Custom hook for adding annotations to an insight
export function useAddAnnotation() {
  const queryClient = useQueryClient();

  return useMutation<InsightAnnotation, Error, { insightId: string | number; note: string }>({
    mutationFn: ({ insightId, note }) => insightsApi.addAnnotation(String(insightId), note),
    onSuccess: (_, variables) => {
      // Invalidate annotation queries
      queryClient.invalidateQueries({ queryKey: annotationKeys.all(variables.insightId) });
      // Invalidate the specific insight detail query
      queryClient.invalidateQueries({ queryKey: insightKeys.detail(String(variables.insightId)) });
      // Invalidate the insights list queries
      queryClient.invalidateQueries({ queryKey: insightKeys.lists() });
    },
  });
}

// Context type for optimistic updates
type AnnotationMutationContext = { previousAnnotations: InsightAnnotation[] | undefined };

// Custom hook for updating an annotation with optimistic updates
export function useUpdateAnnotation() {
  const queryClient = useQueryClient();

  return useMutation<
    InsightAnnotation,
    Error,
    { insightId: string | number; annotationId: number; note: string },
    AnnotationMutationContext
  >({
    mutationFn: ({ insightId, annotationId, note }) =>
      insightsApi.updateAnnotation(String(insightId), annotationId, note),
    onMutate: async ({ insightId, annotationId, note }) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: annotationKeys.all(insightId) });

      // Snapshot previous value
      const previousAnnotations = queryClient.getQueryData<InsightAnnotation[]>(
        annotationKeys.all(insightId)
      );

      // Optimistically update
      if (previousAnnotations) {
        queryClient.setQueryData<InsightAnnotation[]>(
          annotationKeys.all(insightId),
          previousAnnotations.map((annotation) =>
            annotation.id === annotationId
              ? { ...annotation, note, updated_at: new Date().toISOString() }
              : annotation
          )
        );
      }

      return { previousAnnotations };
    },
    onError: (_, { insightId }, context) => {
      // Rollback on error
      if (context?.previousAnnotations) {
        queryClient.setQueryData(annotationKeys.all(insightId), context.previousAnnotations);
      }
    },
    onSettled: (_, __, { insightId }) => {
      // Refetch to ensure server state
      queryClient.invalidateQueries({ queryKey: annotationKeys.all(insightId) });
      queryClient.invalidateQueries({ queryKey: insightKeys.detail(String(insightId)) });
    },
  });
}

// Custom hook for deleting an annotation with optimistic updates
export function useDeleteAnnotation() {
  const queryClient = useQueryClient();

  return useMutation<
    { message: string },
    Error,
    { insightId: string | number; annotationId: number },
    AnnotationMutationContext
  >({
    mutationFn: ({ insightId, annotationId }) =>
      insightsApi.deleteAnnotation(String(insightId), annotationId),
    onMutate: async ({ insightId, annotationId }) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: annotationKeys.all(insightId) });

      // Snapshot previous value
      const previousAnnotations = queryClient.getQueryData<InsightAnnotation[]>(
        annotationKeys.all(insightId)
      );

      // Optimistically remove
      if (previousAnnotations) {
        queryClient.setQueryData<InsightAnnotation[]>(
          annotationKeys.all(insightId),
          previousAnnotations.filter((annotation) => annotation.id !== annotationId)
        );
      }

      return { previousAnnotations };
    },
    onError: (_, { insightId }, context) => {
      // Rollback on error
      if (context?.previousAnnotations) {
        queryClient.setQueryData(annotationKeys.all(insightId), context.previousAnnotations);
      }
    },
    onSettled: (_, __, { insightId }) => {
      // Refetch to ensure server state
      queryClient.invalidateQueries({ queryKey: annotationKeys.all(insightId) });
      queryClient.invalidateQueries({ queryKey: insightKeys.detail(String(insightId)) });
    },
  });
}

// Helper to format relative time
export function formatRelativeTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) {
    return 'just now';
  } else if (diffMins < 60) {
    return `${diffMins} minute${diffMins === 1 ? '' : 's'} ago`;
  } else if (diffHours < 24) {
    return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
  } else if (diffDays < 7) {
    return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
  } else {
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
    });
  }
}

// Helper to get severity color classes
export function getSeverityClasses(severity: Insight['severity']): {
  bg: string;
  text: string;
  border: string;
} {
  switch (severity) {
    case 'alert':
      return {
        bg: 'bg-red-100 dark:bg-red-900/30',
        text: 'text-red-700 dark:text-red-400',
        border: 'border-red-200 dark:border-red-800',
      };
    case 'warning':
      return {
        bg: 'bg-yellow-100 dark:bg-yellow-900/30',
        text: 'text-yellow-700 dark:text-yellow-400',
        border: 'border-yellow-200 dark:border-yellow-800',
      };
    case 'info':
    default:
      return {
        bg: 'bg-blue-100 dark:bg-blue-900/30',
        text: 'text-blue-700 dark:text-blue-400',
        border: 'border-blue-200 dark:border-blue-800',
      };
  }
}

// Helper to get insight type label
export function getInsightTypeLabel(type: Insight['type']): string {
  const labels: Record<Insight['type'], string> = {
    pattern: 'Pattern',
    anomaly: 'Anomaly',
    sector: 'Sector',
    technical: 'Technical',
    economic: 'Economic',
  };
  return labels[type] || type;
}
