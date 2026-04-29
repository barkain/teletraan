'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Play,
  AlertCircle,
  CheckCircle2,
  Loader2,
  ChevronDown,
  TrendingUp,
  Shield,
  Target,
  Clock,
  BarChart3,
  Zap,
} from 'lucide-react';
import {
  useAlphaStatus,
  useAlphaRuns,
  useAlphaRun,
  useStartAlphaRun,
  useAlphaActive,
} from '@/lib/hooks/use-alpha-engine';
import type { AlphaCandidate, AlphaRun } from '@/lib/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(s: string | null): string {
  if (!s) return '--';
  return new Date(s).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '--';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function regimeBadgeVariant(regime: string | null): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (!regime) return 'outline';
  if (regime.includes('risk_off')) return 'destructive';
  if (regime.includes('risk_on')) return 'default';
  return 'secondary';
}

function thesisIcon(thesis: string) {
  if (thesis === 'momentum') return <TrendingUp className="h-3.5 w-3.5" />;
  if (thesis === 'catalyst') return <Zap className="h-3.5 w-3.5" />;
  if (thesis === 'quality_re_rate' || thesis === 're_rating') return <Shield className="h-3.5 w-3.5" />;
  return <Target className="h-3.5 w-3.5" />;
}

function scoreColor(score: number): string {
  if (score >= 70) return 'text-green-600 dark:text-green-400';
  if (score >= 55) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-muted-foreground';
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function RunProgress({ taskId }: { taskId: string }) {
  const { data: status } = useAlphaStatus(taskId);

  if (!status) return null;

  const isRunning = !['completed', 'failed', 'cancelled'].includes(status.status);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">
            {isRunning ? (
              <span className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                Running Analysis
              </span>
            ) : status.status === 'completed' ? (
              <span className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
                Analysis Complete
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-destructive" />
                Analysis Failed
              </span>
            )}
          </CardTitle>
          {status.elapsed_seconds != null && (
            <span className="text-sm text-muted-foreground flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              {formatDuration(status.elapsed_seconds)}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isRunning && (
          <Progress value={status.progress} className="h-2" />
        )}
        {status.phase_details && (
          <p className="text-sm text-muted-foreground">{status.phase_details}</p>
        )}
        {status.status === 'failed' && status.error_message && (
          <p className="text-sm text-destructive">{status.error_message}</p>
        )}
        {status.status === 'completed' && (
          <div className="flex flex-wrap gap-4 text-sm">
            {status.market_regime && (
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Regime:</span>
                <Badge variant={regimeBadgeVariant(status.market_regime)}>
                  {status.market_regime.replace(/_/g, ' ')}
                </Badge>
              </div>
            )}
            {status.universe_size != null && (
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Universe:</span>
                <span className="font-medium">{status.universe_size} symbols</span>
              </div>
            )}
            {status.ideas_persisted != null && (
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Candidates:</span>
                <span className="font-medium">{status.ideas_persisted}</span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CandidatesTable({ candidates }: { candidates: AlphaCandidate[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (candidates.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top Candidates</CardTitle>
        <CardDescription>Ranked by composite alpha score</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">#</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Confidence</TableHead>
              <TableHead>Thesis</TableHead>
              <TableHead>Horizon</TableHead>
              <TableHead className="text-right">Target</TableHead>
              <TableHead className="w-8" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {candidates.map((c) => (
              <>
                <TableRow
                  key={c.id}
                  className="cursor-pointer"
                  onClick={() => setExpanded(expanded === c.id ? null : c.id)}
                >
                  <TableCell className="font-mono text-muted-foreground text-xs">{c.rank}</TableCell>
                  <TableCell>
                    <span className="font-semibold">
                      {c.symbol}
                      {c.is_portfolio_holding && (
                        <Badge variant="outline" className="ml-1.5 text-xs px-1 py-0">held</Badge>
                      )}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className={`font-mono font-semibold ${scoreColor(c.overall_score)}`}>
                      {c.overall_score.toFixed(1)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm">{(c.confidence * 100).toFixed(0)}%</span>
                  </TableCell>
                  <TableCell>
                    <span className="flex items-center gap-1.5 text-sm">
                      {thesisIcon(c.thesis_type)}
                      {c.thesis_type.replace(/_/g, ' ')}
                    </span>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {c.expected_horizon_days ? `${c.expected_horizon_days}d` : '--'}
                  </TableCell>
                  <TableCell className="text-right text-sm">
                    {c.target_price ? `$${c.target_price.toFixed(2)}` : '--'}
                  </TableCell>
                  <TableCell>
                    <ChevronDown
                      className={`h-4 w-4 text-muted-foreground transition-transform ${expanded === c.id ? 'rotate-180' : ''}`}
                    />
                  </TableCell>
                </TableRow>
                {expanded === c.id && (
                  <TableRow key={`${c.id}-detail`}>
                    <TableCell colSpan={8} className="bg-muted/30 p-4">
                      <div className="grid gap-3 text-sm">
                        {c.bull_case && (
                          <div>
                            <p className="font-medium text-green-600 dark:text-green-400 mb-1">Bull case</p>
                            <p className="text-muted-foreground">{c.bull_case}</p>
                          </div>
                        )}
                        {c.bear_case && (
                          <div>
                            <p className="font-medium text-red-600 dark:text-red-400 mb-1">Bear case</p>
                            <p className="text-muted-foreground">{c.bear_case}</p>
                          </div>
                        )}
                        {c.portfolio_relevance && (
                          <div>
                            <p className="font-medium mb-1">Portfolio relevance</p>
                            <p className="text-muted-foreground">{c.portfolio_relevance}</p>
                          </div>
                        )}
                        {c.key_drivers && c.key_drivers.length > 0 && (
                          <div>
                            <p className="font-medium mb-1">Key drivers</p>
                            <div className="flex flex-wrap gap-1.5">
                              {c.key_drivers.map((d) => (
                                <Badge key={d} variant="outline" className="text-xs font-mono">{d}</Badge>
                              ))}
                            </div>
                          </div>
                        )}
                        {c.stop_price && (
                          <p className="text-muted-foreground">
                            Stop guide: <span className="font-mono">${c.stop_price.toFixed(2)}</span>
                          </p>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function RunDetail({ runId }: { runId: string }) {
  const { data, isLoading } = useAlphaRun(runId);

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }
  if (!data) return null;

  return <CandidatesTable candidates={data.candidates} />;
}

function PastRunRow({ run, onSelect }: { run: AlphaRun; onSelect: (id: string) => void }) {
  return (
    <TableRow
      className="cursor-pointer hover:bg-muted/50"
      onClick={() => onSelect(run.id)}
    >
      <TableCell className="text-sm">{formatDate(run.started_at)}</TableCell>
      <TableCell>
        <Badge variant={regimeBadgeVariant(run.market_regime)}>
          {run.market_regime ? run.market_regime.replace(/_/g, ' ') : 'unknown'}
        </Badge>
      </TableCell>
      <TableCell className="text-sm">{run.universe_size}</TableCell>
      <TableCell className="text-sm">{run.ideas_persisted}</TableCell>
      <TableCell>
        <Badge variant={run.status === 'completed' ? 'default' : run.status === 'failed' ? 'destructive' : 'secondary'}>
          {run.status}
        </Badge>
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AlphaEnginePage() {
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Check for active run on mount (page-reload resilience)
  const { data: activeTask } = useAlphaActive();
  useEffect(() => {
    if (activeTask && !activeTaskId) {
      setActiveTaskId(activeTask.task_id);
    }
  }, [activeTask, activeTaskId]);

  // Load from localStorage as a fallback
  useEffect(() => {
    const stored = localStorage.getItem('alpha_task_id');
    if (stored && !activeTaskId) {
      setActiveTaskId(stored);
    }
  }, [activeTaskId]);

  const { data: taskStatus } = useAlphaStatus(activeTaskId);

  // When run completes, show its detail automatically
  useEffect(() => {
    if (taskStatus?.status === 'completed' && taskStatus.analysis_run_id && !selectedRunId) {
      setSelectedRunId(taskStatus.analysis_run_id);
    }
  }, [taskStatus, selectedRunId]);

  const startRun = useStartAlphaRun();
  const { data: runsData, isLoading: runsLoading } = useAlphaRuns({ limit: 10 });

  const isRunning =
    taskStatus && !['completed', 'failed', 'cancelled'].includes(taskStatus.status);

  const handleStart = async () => {
    const result = await startRun.mutateAsync();
    setActiveTaskId(result.task_id);
    setSelectedRunId(null);
    localStorage.setItem('alpha_task_id', result.task_id);
  };

  return (
    <div className="container max-w-5xl py-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BarChart3 className="h-6 w-6 text-primary" />
            Alpha Engine
          </h1>
          <p className="text-muted-foreground mt-1">
            Factor-based market-wide screening — no symbols required
          </p>
        </div>
        <Button
          onClick={handleStart}
          disabled={!!isRunning || startRun.isPending}
          size="lg"
        >
          {isRunning || startRun.isPending ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Running…
            </>
          ) : (
            <>
              <Play className="h-4 w-4 mr-2" />
              Run Analysis
            </>
          )}
        </Button>
      </div>

      {/* Progress card */}
      {activeTaskId && <RunProgress taskId={activeTaskId} />}

      {/* Candidate results */}
      {selectedRunId && <RunDetail runId={selectedRunId} />}

      {/* Past runs */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Past Runs</CardTitle>
          <CardDescription>Click a row to view its candidates</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {runsLoading ? (
            <div className="p-4 space-y-2">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !runsData?.items?.length ? (
            <div className="p-8 text-center text-muted-foreground text-sm">
              No runs yet — click &quot;Run Analysis&quot; to start.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Started</TableHead>
                  <TableHead>Regime</TableHead>
                  <TableHead>Universe</TableHead>
                  <TableHead>Candidates</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runsData.items.map((run) => (
                  <PastRunRow
                    key={run.id}
                    run={run}
                    onSelect={(id) => {
                      setSelectedRunId(selectedRunId === id ? null : id);
                    }}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
