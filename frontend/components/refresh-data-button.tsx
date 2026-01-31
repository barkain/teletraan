'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useRefreshData } from '@/lib/hooks/use-refresh-data';
import { RefreshProgressDialog, RefreshStage, RefreshResult } from '@/components/refresh-progress-dialog';

// Stage timing configuration (in milliseconds from start)
const STAGE_TIMINGS = {
  fetching: 0,        // Start immediately
  analyzing: 2000,    // After 2 seconds
  generating: 30000,  // After 30 seconds
} as const;

export function RefreshDataButton() {
  const { mutate: refresh, isPending } = useRefreshData();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [stage, setStage] = useState<RefreshStage>('idle');
  const [result, setResult] = useState<RefreshResult | undefined>();
  const [error, setError] = useState<string | undefined>();

  const startTimeRef = useRef<number | null>(null);
  const stageIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Update stage based on elapsed time
  const updateStageByTime = useCallback(() => {
    if (!startTimeRef.current || stage === 'complete' || stage === 'error') {
      return;
    }

    const elapsed = Date.now() - startTimeRef.current;

    if (elapsed >= STAGE_TIMINGS.generating) {
      setStage('generating');
    } else if (elapsed >= STAGE_TIMINGS.analyzing) {
      setStage('analyzing');
    } else {
      setStage('fetching');
    }
  }, [stage]);

  // Clean up interval on unmount or when refresh completes
  useEffect(() => {
    return () => {
      if (stageIntervalRef.current) {
        clearInterval(stageIntervalRef.current);
      }
    };
  }, []);

  const handleRefresh = () => {
    // Reset state
    setStage('fetching');
    setResult(undefined);
    setError(undefined);
    setDialogOpen(true);
    startTimeRef.current = Date.now();

    // Start stage progression timer
    if (stageIntervalRef.current) {
      clearInterval(stageIntervalRef.current);
    }
    stageIntervalRef.current = setInterval(updateStageByTime, 500);

    refresh(undefined, {
      onSuccess: (data) => {
        // Clear the interval
        if (stageIntervalRef.current) {
          clearInterval(stageIntervalRef.current);
          stageIntervalRef.current = null;
        }

        setResult({
          symbols_updated: data.symbols_updated.length,
          records_added: data.records_added,
          // These would come from the API in a real implementation
          insights_generated: data.symbols_updated.length * 3,
          deep_insights_generated: data.symbols_updated.length,
        });
        setStage('complete');
      },
      onError: (err) => {
        // Clear the interval
        if (stageIntervalRef.current) {
          clearInterval(stageIntervalRef.current);
          stageIntervalRef.current = null;
        }

        setError(err.message);
        setStage('error');
      },
    });
  };

  const handleDialogClose = (open: boolean) => {
    // Only allow closing when complete or error
    if (!open && (stage === 'complete' || stage === 'error')) {
      setDialogOpen(false);
      setStage('idle');
    }
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={handleRefresh}
        disabled={isPending}
      >
        <RefreshCw className={`h-4 w-4 mr-2 ${isPending ? 'animate-spin' : ''}`} />
        {isPending ? 'Refreshing...' : 'Refresh Data'}
      </Button>

      <RefreshProgressDialog
        open={dialogOpen}
        onOpenChange={handleDialogClose}
        stage={stage}
        result={result}
        error={error}
      />
    </>
  );
}
