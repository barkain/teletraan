'use client';

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import { CheckCircle2, Loader2, Database, Brain, Sparkles, XCircle } from 'lucide-react';

export type RefreshStage = 'idle' | 'fetching' | 'analyzing' | 'generating' | 'complete' | 'error';

export interface RefreshResult {
  symbols_updated: number;
  records_added: number;
  insights_generated?: number;
  deep_insights_generated?: number;
}

interface RefreshProgressDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stage: RefreshStage;
  result?: RefreshResult;
  error?: string;
}

const stages = [
  { key: 'fetching', label: 'Fetching market data...', icon: Database, progress: 25 },
  { key: 'analyzing', label: 'Running analyst team (5 agents)...', icon: Brain, progress: 60 },
  { key: 'generating', label: 'Synthesizing insights...', icon: Sparkles, progress: 85 },
  { key: 'complete', label: 'Complete!', icon: CheckCircle2, progress: 100 },
] as const;

export function RefreshProgressDialog({
  open,
  onOpenChange,
  stage,
  result,
  error
}: RefreshProgressDialogProps) {
  const currentStageIndex = stages.findIndex(s => s.key === stage);
  const currentStage = currentStageIndex >= 0 ? stages[currentStageIndex] : stages[0];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" showCloseButton={stage === 'complete' || stage === 'error'}>
        <DialogHeader>
          <DialogTitle>Refreshing Market Data</DialogTitle>
        </DialogHeader>

        <div className="space-y-6 py-4">
          {/* Progress Bar */}
          <Progress
            value={stage === 'error' ? 0 : currentStage.progress}
            className="h-2 transition-all duration-500"
          />

          {/* Current Stage Status */}
          <div className="flex items-center gap-3">
            {stage === 'complete' ? (
              <CheckCircle2 className="w-6 h-6 text-green-500 shrink-0" />
            ) : stage === 'error' ? (
              <XCircle className="w-6 h-6 text-red-500 shrink-0" />
            ) : (
              <Loader2 className="w-6 h-6 animate-spin text-primary shrink-0" />
            )}
            <span className="text-lg font-medium">
              {stage === 'error' ? 'Refresh failed' : currentStage.label}
            </span>
          </div>

          {/* Stage Steps */}
          <div className="space-y-3">
            {stages.map((s, i) => {
              const isCompleted = currentStageIndex > i || stage === 'complete';
              const isCurrent = currentStageIndex === i && stage !== 'complete' && stage !== 'error';
              const Icon = s.icon;

              return (
                <div
                  key={s.key}
                  className={`flex items-center gap-3 text-sm transition-all duration-300 ${
                    isCompleted ? 'text-green-500' :
                    isCurrent ? 'text-primary font-medium' :
                    'text-muted-foreground'
                  }`}
                >
                  {isCompleted ? (
                    <CheckCircle2 className="w-4 h-4 shrink-0" />
                  ) : isCurrent ? (
                    <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                  ) : (
                    <Icon className="w-4 h-4 shrink-0 opacity-50" />
                  )}
                  <span>{s.label}</span>
                </div>
              );
            })}
          </div>

          {/* Error Message */}
          {stage === 'error' && error && (
            <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 rounded-lg p-4 text-sm text-red-700 dark:text-red-400">
              {error}
            </div>
          )}

          {/* Results */}
          {stage === 'complete' && result && (
            <div className="bg-muted rounded-lg p-4 space-y-2 text-sm animate-in fade-in-0 duration-300">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-green-500" />
                <span>{result.symbols_updated} symbols updated</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-green-500" />
                <span>{result.records_added} price records added</span>
              </div>
              {result.insights_generated !== undefined && (
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-green-500" />
                  <span>{result.insights_generated} basic insights generated</span>
                </div>
              )}
              {result.deep_insights_generated !== undefined && (
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-green-500" />
                  <span>{result.deep_insights_generated} deep insights generated</span>
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
