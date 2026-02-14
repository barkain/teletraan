'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { fetchApi, postApi } from '@/lib/api';
import { deepInsightKeys } from '@/lib/hooks/use-deep-insights';

// ============================================
// Types
// ============================================

export interface LLMActivityEntry {
  seq: number;
  timestamp: string;
  phase: string;
  agent_name: string;
  prompt_preview: string;
  response_preview: string;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  status: 'running' | 'done' | 'error';
}

export interface AnalysisTaskStatus {
  id: string;
  status: string;
  progress: number;
  current_phase: string | null;
  phase_details: string | null;
  phase_name: string | null;
  result_insight_ids: number[] | null;
  result_analysis_id: string | null;
  market_regime: string | null;
  top_sectors: string[] | null;
  discovery_summary: string | null;
  phases_completed: string[] | null;
  error_message: string | null;
  elapsed_seconds: number | null;
  started_at: string | null;
  completed_at: string | null;
  activity?: LLMActivityEntry[] | null;
}

export interface StartAnalysisResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface UseAnalysisTaskOptions {
  pollInterval?: number; // Polling interval in ms (default: 2000)
  onComplete?: (task: AnalysisTaskStatus) => void;
  onError?: (error: string) => void;
}

export interface UseAnalysisTaskResult {
  // Current state
  taskId: string | null;
  task: AnalysisTaskStatus | null;
  isRunning: boolean;
  isComplete: boolean;
  isFailed: boolean;
  isCancelled: boolean;
  error: string | null;
  elapsedSeconds: number;
  activityLog: LLMActivityEntry[];

  // Actions
  startAnalysis: (params?: { max_insights?: number; deep_dive_count?: number }) => Promise<void>;
  cancelAnalysis: () => Promise<void>;
  checkForActiveTask: () => Promise<AnalysisTaskStatus | null>;
  clearTask: () => void;
}

// LocalStorage key for persisting task ID
const TASK_ID_STORAGE_KEY = 'market-analyzer-analysis-task-id';

// ============================================
// API Functions
// ============================================

async function startBackgroundAnalysis(params?: {
  max_insights?: number;
  deep_dive_count?: number;
}): Promise<StartAnalysisResponse> {
  return postApi<StartAnalysisResponse>('/api/v1/deep-insights/autonomous/start', params);
}

async function getTaskStatus(taskId: string, sinceActivitySeq: number = 0): Promise<AnalysisTaskStatus> {
  return fetchApi<AnalysisTaskStatus>(
    `/api/v1/deep-insights/autonomous/status/${taskId}?since_activity_seq=${sinceActivitySeq}`
  );
}

async function getActiveTask(): Promise<AnalysisTaskStatus | null> {
  try {
    const response = await fetchApi<AnalysisTaskStatus | null>(
      '/api/v1/deep-insights/autonomous/active'
    );
    return response;
  } catch {
    return null;
  }
}

async function cancelTask(taskId: string): Promise<{ status: string; message: string }> {
  return postApi<{ task_id: string; status: string; message: string }>(
    `/api/v1/deep-insights/autonomous/cancel/${taskId}`
  );
}

// ============================================
// Hook Implementation
// ============================================

export function useAnalysisTask(options: UseAnalysisTaskOptions = {}): UseAnalysisTaskResult {
  const { pollInterval = 2000, onComplete, onError } = options;
  const queryClient = useQueryClient();

  // State
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<AnalysisTaskStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [_startTime, setStartTime] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const [activityLog, setActivityLog] = useState<LLMActivityEntry[]>([]);
  const [activitySeqCursor, setActivitySeqCursor] = useState<number>(0);

  // Refs for callbacks to avoid stale closures
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  onCompleteRef.current = onComplete;
  onErrorRef.current = onError;

  // Polling ref
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Timer ref for elapsed time
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Ref to track if startAnalysis is in progress (guards against checkForActiveTask race)
  const isStartingRef = useRef<boolean>(false);

  // Derived state
  const isRunning = task !== null && !['completed', 'failed', 'cancelled'].includes(task.status);
  const isComplete = task?.status === 'completed';
  const isFailed = task?.status === 'failed';
  const isCancelled = task?.status === 'cancelled';

  // Stop elapsed timer
  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Start elapsed timer
  const startTimer = useCallback((fromTime?: number) => {
    stopTimer();
    const start = fromTime ?? Date.now();
    setStartTime(start);
    setElapsedSeconds(Math.floor((Date.now() - start) / 1000));

    timerRef.current = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - start) / 1000));
    }, 1000);
  }, [stopTimer]);

  // Stop polling
  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    stopTimer();
  }, [stopTimer]);

  // Start polling for task status
  const startPolling = useCallback(
    (id: string, existingStartTime?: number) => {
      stopPolling();

      // Start the elapsed timer
      startTimer(existingStartTime);

      const poll = async () => {
        try {
          const status = await getTaskStatus(id, activitySeqCursor);
          setTask(status);

          // Merge new activity entries incrementally
          if (status.activity && status.activity.length > 0) {
            setActivityLog((prev) => {
              const merged = [...prev, ...status.activity!];
              // Update cursor to highest seq number
              const maxSeq = Math.max(...merged.map((e) => e.seq));
              setActivitySeqCursor(maxSeq);
              return merged;
            });
          }

          if (status.status === 'completed') {
            stopPolling();
            // Invalidate insights queries to refresh the list
            queryClient.invalidateQueries({ queryKey: deepInsightKeys.all });
            onCompleteRef.current?.(status);
            // Clear from localStorage since we're done
            localStorage.removeItem(TASK_ID_STORAGE_KEY);
          } else if (status.status === 'failed') {
            stopPolling();
            setError(status.error_message || 'Analysis failed');
            onErrorRef.current?.(status.error_message || 'Analysis failed');
            localStorage.removeItem(TASK_ID_STORAGE_KEY);
          } else if (status.status === 'cancelled') {
            stopPolling();
            localStorage.removeItem(TASK_ID_STORAGE_KEY);
          }
        } catch (err) {
          console.error('Error polling task status:', err);
          // Don't stop polling on transient errors
        }
      };

      // Poll immediately, then at interval
      poll();
      pollingRef.current = setInterval(poll, pollInterval);
    },
    [pollInterval, queryClient, stopPolling, startTimer]
  );

  // Start a new analysis
  const startAnalysis = useCallback(
    async (params?: { max_insights?: number; deep_dive_count?: number }) => {
      try {
        // Guard against checkForActiveTask race condition
        isStartingRef.current = true;

        // Reset timer and state immediately BEFORE the async call
        // so no stale elapsed time is visible during the await
        stopPolling();
        setError(null);
        setElapsedSeconds(0);
        setStartTime(null);
        setActivityLog([]);
        setActivitySeqCursor(0);

        const response = await startBackgroundAnalysis(params);

        // Save task ID to localStorage for persistence
        localStorage.setItem(TASK_ID_STORAGE_KEY, response.task_id);
        setTaskId(response.task_id);

        // Record start time
        const now = Date.now();

        // Initialize task state
        setTask({
          id: response.task_id,
          status: 'pending',
          progress: 0,
          current_phase: 'pending',
          phase_details: 'Initializing...',
          phase_name: 'Initializing...',
          result_insight_ids: null,
          result_analysis_id: null,
          market_regime: null,
          top_sectors: null,
          discovery_summary: null,
          phases_completed: null,
          error_message: null,
          elapsed_seconds: null,
          started_at: null,
          completed_at: null,
        });

        // Start polling with current time as start
        startPolling(response.task_id, now);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to start analysis';
        setError(message);
        onErrorRef.current?.(message);
      } finally {
        isStartingRef.current = false;
      }
    },
    [startPolling, stopPolling]
  );

  // Cancel running analysis
  const cancelAnalysis = useCallback(async () => {
    if (!taskId) return;

    try {
      await cancelTask(taskId);
      stopPolling();
      // Update local state immediately
      setTask((prev) =>
        prev
          ? {
              ...prev,
              status: 'cancelled',
              phase_details: 'Analysis cancelled by user',
            }
          : null
      );
      localStorage.removeItem(TASK_ID_STORAGE_KEY);
    } catch (err) {
      console.error('Failed to cancel analysis:', err);
    }
  }, [taskId, stopPolling]);

  // Check for active task (on mount or manual check)
  const checkForActiveTask = useCallback(async (): Promise<AnalysisTaskStatus | null> => {
    // First check localStorage for a saved task ID
    const savedTaskId = localStorage.getItem(TASK_ID_STORAGE_KEY);

    if (savedTaskId) {
      try {
        const status = await getTaskStatus(savedTaskId);

        // Bail out if startAnalysis was called while we were awaiting
        if (isStartingRef.current) return null;

        // If task is still running, resume polling
        if (!['completed', 'failed', 'cancelled'].includes(status.status)) {
          setTaskId(savedTaskId);
          setTask(status);
          // Calculate start time from task's started_at if available
          // Backend returns UTC datetime without timezone suffix (e.g. "2026-02-08T10:30:00")
          // so we must append 'Z' to ensure JS interprets it as UTC, not local time
          const existingStartTime = status.started_at
            ? new Date(status.started_at.endsWith('Z') ? status.started_at : status.started_at + 'Z').getTime()
            : undefined;
          startPolling(savedTaskId, existingStartTime);
          return status;
        }

        // Task is done, clear from storage
        localStorage.removeItem(TASK_ID_STORAGE_KEY);

        // If completed, still show the result
        if (status.status === 'completed') {
          setTaskId(savedTaskId);
          setTask(status);
          return status;
        }
      } catch {
        // Task not found, clear storage
        localStorage.removeItem(TASK_ID_STORAGE_KEY);
      }
    }

    // Also check the server for any active task
    const activeTask = await getActiveTask();

    // Bail out if startAnalysis was called while we were awaiting
    if (isStartingRef.current) return null;

    if (activeTask) {
      localStorage.setItem(TASK_ID_STORAGE_KEY, activeTask.id);
      setTaskId(activeTask.id);
      setTask(activeTask);

      if (!['completed', 'failed', 'cancelled'].includes(activeTask.status)) {
        // Calculate start time from task's started_at if available
        // Backend returns UTC datetime without timezone suffix — append 'Z' so JS parses as UTC
        const existingStartTime = activeTask.started_at
          ? new Date(activeTask.started_at.endsWith('Z') ? activeTask.started_at : activeTask.started_at + 'Z').getTime()
          : undefined;
        startPolling(activeTask.id, existingStartTime);
      }

      return activeTask;
    }

    return null;
  }, [startPolling]);

  // Clear task state
  const clearTask = useCallback(() => {
    stopPolling();
    setTaskId(null);
    setTask(null);
    setError(null);
    setStartTime(null);
    setElapsedSeconds(0);
    setActivityLog([]);
    setActivitySeqCursor(0);
    localStorage.removeItem(TASK_ID_STORAGE_KEY);
  }, [stopPolling]);

  // Check for active task on mount - non-blocking
  // Use a microtask to avoid blocking the initial render
  useEffect(() => {
    // Defer the check to not block initial render
    const timeoutId = setTimeout(() => {
      checkForActiveTask();
    }, 0);

    return () => {
      clearTimeout(timeoutId);
      stopPolling();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    taskId,
    task,
    isRunning,
    isComplete,
    isFailed,
    isCancelled,
    error,
    elapsedSeconds,
    activityLog,
    startAnalysis,
    cancelAnalysis,
    checkForActiveTask,
    clearTask,
  };
}
