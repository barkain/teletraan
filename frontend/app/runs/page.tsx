'use client';

import React, { useState, useMemo, useCallback } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
} from 'recharts';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ConnectionError } from '@/components/ui/empty-state';
import { useRuns, useRunsStats } from '@/lib/hooks/use-runs';
import type { RunSummary, PhaseTimingDetail, PhaseTokenUsageDetail } from '@/types';
import {
  Search,
  Activity,
  Clock,
  DollarSign,
  Zap,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  ArrowUpDown,
  AlertCircle,
  PlayCircle,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatShortDate(dateStr: string | null): string {
  if (!dateStr) return '--';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', {
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
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

function formatCost(cost: number | null): string {
  if (cost == null) return '--';
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

function formatTokens(count: number | null): string {
  if (count == null) return '--';
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return count.toLocaleString();
}

function formatNumber(n: number): string {
  return n.toLocaleString();
}

// ---------------------------------------------------------------------------
// Status badge colors
// ---------------------------------------------------------------------------

const STATUS_BADGE: Record<string, string> = {
  completed: 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-300',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-300',
  running: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/60 dark:text-yellow-300',
  pending: 'bg-blue-100 text-blue-800 dark:bg-blue-900/60 dark:text-blue-300',
};

function getStatusBadgeClass(status: string): string {
  return STATUS_BADGE[status.toLowerCase()] ?? 'bg-muted text-muted-foreground';
}

// ---------------------------------------------------------------------------
// Sort helpers
// ---------------------------------------------------------------------------

type SortField = 'date' | 'duration' | 'cost' | 'tokens' | 'insights';
type SortDir = 'asc' | 'desc';

function compareRuns(a: RunSummary, b: RunSummary, field: SortField, dir: SortDir): number {
  let cmp = 0;
  switch (field) {
    case 'date': {
      const da = a.created_at ?? '';
      const db = b.created_at ?? '';
      cmp = da.localeCompare(db);
      break;
    }
    case 'duration':
      cmp = (a.elapsed_seconds ?? 0) - (b.elapsed_seconds ?? 0);
      break;
    case 'cost':
      cmp = (a.total_cost_usd ?? 0) - (b.total_cost_usd ?? 0);
      break;
    case 'tokens':
      cmp = ((a.total_input_tokens ?? 0) + (a.total_output_tokens ?? 0)) -
            ((b.total_input_tokens ?? 0) + (b.total_output_tokens ?? 0));
      break;
    case 'insights':
      cmp = (a.result_insight_ids?.length ?? a.deep_dive_count ?? 0) -
            (b.result_insight_ids?.length ?? b.deep_dive_count ?? 0);
      break;
  }
  return dir === 'asc' ? cmp : -cmp;
}

// ---------------------------------------------------------------------------
// Chart colors
// ---------------------------------------------------------------------------

const CHART_BLUE = '#3b82f6';
const CHART_GREEN = '#22c55e';
const CHART_GRID = '#374151';

// Phase colors for waterfall
const PHASE_COLORS: string[] = [
  '#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6',
  '#ec4899', '#06b6d4', '#f97316', '#a855f7',
];

// ---------------------------------------------------------------------------
// Stat Cards
// ---------------------------------------------------------------------------

function StatsCards({
  totalRuns,
  totalCost,
  avgDuration,
  totalTokens,
  isLoading,
}: {
  totalRuns: number;
  totalCost: number;
  avgDuration: number | null;
  totalTokens: number;
  isLoading: boolean;
}) {
  const items = [
    {
      icon: Activity,
      label: 'Total Runs',
      value: isLoading ? '...' : formatNumber(totalRuns),
    },
    {
      icon: DollarSign,
      label: 'Total Cost',
      value: isLoading ? '...' : formatCost(totalCost),
    },
    {
      icon: Clock,
      label: 'Avg Duration',
      value: isLoading ? '...' : formatDuration(avgDuration),
    },
    {
      icon: Zap,
      label: 'Total Tokens',
      value: isLoading ? '...' : formatTokens(totalTokens),
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {items.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-3 px-4 py-3 rounded-lg bg-card/80 backdrop-blur-sm border border-border/50"
        >
          <item.icon className="h-4 w-4 text-muted-foreground shrink-0" />
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground truncate">{item.label}</p>
            <p className="text-sm font-semibold truncate">{item.value}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

function FilterBar({
  statusFilter,
  onStatusChange,
  search,
  onSearchChange,
}: {
  statusFilter: string;
  onStatusChange: (v: string) => void;
  search: string;
  onSearchChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col md:flex-row gap-3 items-start md:items-center">
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search runs..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
        />
      </div>
      <Select value={statusFilter} onValueChange={onStatusChange}>
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="All Statuses" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Statuses</SelectItem>
          <SelectItem value="completed">Completed</SelectItem>
          <SelectItem value="failed">Failed</SelectItem>
          <SelectItem value="running">Running</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------

function DurationChart({ runs }: { runs: RunSummary[] }) {
  const chartData = useMemo(() => {
    // Sort chronologically (oldest first) so the chart reads left-to-right
    const sorted = runs
      .filter((r) => r.elapsed_seconds != null)
      .sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''));
    return sorted.map((r) => ({
      label: r.created_at
        ? new Date(r.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
        : '?',
      duration: Math.round(r.elapsed_seconds ?? 0),
      status: r.status,
    }));
  }, [runs]);

  if (chartData.length === 0) return null;

  return (
    <Card className="bg-card/80 backdrop-blur-sm border border-border/50">
      <CardContent className="pt-6">
        <p className="text-sm font-medium mb-4">Duration per Run (seconds)</p>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} opacity={0.3} />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#9ca3af" />
            <YAxis tick={{ fontSize: 11 }} stroke="#9ca3af" />
            <RechartsTooltip
              cursor={false}
              contentStyle={{
                backgroundColor: 'hsl(var(--card))',
                border: '1px solid hsl(var(--border))',
                borderRadius: '8px',
                fontSize: 12,
              }}
              formatter={(value: number | undefined) => [`${formatDuration(value ?? 0)}`, 'Duration']}
            />
            <Bar dataKey="duration" fill={CHART_BLUE} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

function CostChart({ runs }: { runs: RunSummary[] }) {
  const chartData = useMemo(() => {
    // Sort chronologically (oldest first) so the chart reads left-to-right
    const sorted = runs
      .filter((r) => r.total_cost_usd != null)
      .sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''));
    return sorted.map((r) => ({
      label: r.created_at
        ? new Date(r.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
        : '?',
      cost: Number((r.total_cost_usd ?? 0).toFixed(4)),
    }));
  }, [runs]);

  if (chartData.length === 0) return null;

  return (
    <Card className="bg-card/80 backdrop-blur-sm border border-border/50">
      <CardContent className="pt-6">
        <p className="text-sm font-medium mb-4">Cost Trend (USD)</p>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} opacity={0.3} />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#9ca3af" />
            <YAxis tick={{ fontSize: 11 }} stroke="#9ca3af" tickFormatter={(v) => `$${v}`} />
            <RechartsTooltip
              cursor={false}
              contentStyle={{
                backgroundColor: 'hsl(var(--card))',
                border: '1px solid hsl(var(--border))',
                borderRadius: '8px',
                fontSize: 12,
              }}
              formatter={(value: number | undefined) => [`$${(value ?? 0).toFixed(4)}`, 'Cost']}
            />
            <Line
              type="monotone"
              dataKey="cost"
              stroke={CHART_GREEN}
              strokeWidth={2}
              dot={{ fill: CHART_GREEN, r: 3 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sortable Table Header
// ---------------------------------------------------------------------------

function SortableHeader({
  label,
  field,
  sortField,
  sortDir,
  onSort,
  className,
}: {
  label: string;
  field: SortField;
  sortField: SortField;
  sortDir: SortDir;
  onSort: (f: SortField) => void;
  className?: string;
}) {
  const isActive = sortField === field;
  return (
    <TableHead
      className={`cursor-pointer select-none hover:text-foreground transition-colors ${className ?? ''}`}
      onClick={() => onSort(field)}
    >
      <div className="flex items-center gap-1">
        {label}
        {isActive ? (
          sortDir === 'asc' ? (
            <ChevronUp className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-40" />
        )}
      </div>
    </TableHead>
  );
}

// ---------------------------------------------------------------------------
// Expandable Row Detail — Phase waterfall + token breakdown
// ---------------------------------------------------------------------------

function PhaseWaterfall({
  phaseTimings,
  totalDuration,
}: {
  phaseTimings: Record<string, PhaseTimingDetail>;
  totalDuration: number;
}) {
  const phases = Object.entries(phaseTimings).sort(
    ([, a], [, b]) => new Date(a.start).getTime() - new Date(b.start).getTime()
  );

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground mb-2">Phase Timing Waterfall</p>
      {phases.map(([name, timing], i) => {
        const pct = totalDuration > 0 ? (timing.duration_seconds / totalDuration) * 100 : 0;
        return (
          <div key={name} className="flex items-center gap-2">
            <span className="text-xs w-32 truncate text-muted-foreground capitalize">
              {name.replace(/_/g, ' ')}
            </span>
            <div className="flex-1 h-4 bg-muted/30 rounded overflow-hidden relative">
              <div
                className="h-full rounded"
                style={{
                  width: `${Math.max(pct, 2)}%`,
                  backgroundColor: PHASE_COLORS[i % PHASE_COLORS.length],
                }}
              />
            </div>
            <span className="text-xs font-mono w-16 text-right">
              {formatDuration(timing.duration_seconds)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function PhaseTokenTable({
  phaseTokenUsage,
}: {
  phaseTokenUsage: Record<string, PhaseTokenUsageDetail>;
}) {
  const phases = Object.entries(phaseTokenUsage);

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground mb-2">Per-Phase Token Usage</p>
      <div className="rounded border border-border/50 overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Phase</TableHead>
              <TableHead className="text-xs text-right">Input</TableHead>
              <TableHead className="text-xs text-right">Output</TableHead>
              <TableHead className="text-xs text-right">Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {phases.map(([name, usage]) => (
              <TableRow key={name}>
                <TableCell className="text-xs capitalize">{name.replace(/_/g, ' ')}</TableCell>
                <TableCell className="text-xs text-right font-mono">
                  {formatTokens(usage.input_tokens)}
                </TableCell>
                <TableCell className="text-xs text-right font-mono">
                  {formatTokens(usage.output_tokens)}
                </TableCell>
                <TableCell className="text-xs text-right font-mono">
                  {formatCost(usage.cost_usd)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function ExpandedRowDetail({ run }: { run: RunSummary }) {
  const hasPhaseTimings = run.phase_timings && Object.keys(run.phase_timings).length > 0;
  const hasPhaseTokens = run.phase_token_usage && Object.keys(run.phase_token_usage).length > 0;

  if (!hasPhaseTimings && !hasPhaseTokens) {
    return (
      <div className="px-4 py-6 text-center text-sm text-muted-foreground">
        No phase data available for this run.
      </div>
    );
  }

  return (
    <div className="px-4 py-4 grid gap-6 md:grid-cols-2">
      {hasPhaseTimings && (
        <PhaseWaterfall
          phaseTimings={run.phase_timings!}
          totalDuration={run.elapsed_seconds ?? 0}
        />
      )}
      {hasPhaseTokens && <PhaseTokenTable phaseTokenUsage={run.phase_token_usage!} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Runs Table
// ---------------------------------------------------------------------------

function RunsTable({ runs }: { runs: RunSummary[] }) {
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleSort = useCallback(
    (field: SortField) => {
      if (field === sortField) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortField(field);
        setSortDir('desc');
      }
    },
    [sortField],
  );

  const sorted = useMemo(
    () => [...runs].sort((a, b) => compareRuns(a, b, sortField, sortDir)),
    [runs, sortField, sortDir],
  );

  const toggleExpand = useCallback((id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  if (sorted.length === 0) {
    return (
      <Card className="py-12">
        <CardContent className="flex flex-col items-center justify-center text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <Search className="h-8 w-8 text-muted-foreground" />
          </div>
          <CardTitle className="text-lg mb-2">No Runs Found</CardTitle>
          <CardDescription className="max-w-sm">
            No analysis runs match the current filters. Try adjusting your search or status filter.
          </CardDescription>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="rounded-lg border border-border/50 bg-card/80 backdrop-blur-sm overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <SortableHeader
              label="Date"
              field="date"
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
            />
            <TableHead>Status</TableHead>
            <SortableHeader
              label="Duration"
              field="duration"
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
            />
            <TableHead>Model</TableHead>
            <SortableHeader
              label="Tokens"
              field="tokens"
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
            />
            <SortableHeader
              label="Cost"
              field="cost"
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
            />
            <SortableHeader
              label="Insights"
              field="insights"
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
              className="text-center"
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((run) => {
            const isExpanded = expandedId === run.id;
            const insightCount = run.result_insight_ids?.length ?? run.deep_dive_count ?? null;
            const totalTokens =
              run.total_input_tokens != null || run.total_output_tokens != null
                ? `${formatTokens(run.total_input_tokens)} / ${formatTokens(run.total_output_tokens)}`
                : '--';

            return (
              <React.Fragment key={run.id}>
                <TableRow
                  className="cursor-pointer hover:bg-muted/50 transition-colors"
                  onClick={() => toggleExpand(run.id)}
                >
                  <TableCell className="font-medium">
                    {formatShortDate(run.created_at)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className={`text-xs capitalize ${getStatusBadgeClass(run.status)}`}
                    >
                      {run.status === 'running' && (
                        <PlayCircle className="h-3 w-3 mr-1 animate-spin" />
                      )}
                      {run.status === 'failed' && (
                        <AlertCircle className="h-3 w-3 mr-1" />
                      )}
                      {run.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {formatDuration(run.elapsed_seconds)}
                  </TableCell>
                  <TableCell className="text-sm">
                    {run.model_used ?? '--'}
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {totalTokens}
                  </TableCell>
                  <TableCell className="font-mono text-sm">
                    {formatCost(run.total_cost_usd)}
                  </TableCell>
                  <TableCell className="text-center">
                    {insightCount != null ? insightCount : '--'}
                  </TableCell>
                </TableRow>
                {isExpanded && (
                  <TableRow>
                    <TableCell colSpan={7} className="p-0 bg-muted/20">
                      <ExpandedRowDetail run={run} />
                    </TableCell>
                  </TableRow>
                )}
              </React.Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

function Pagination({
  currentPage,
  totalPages,
  onPageChange,
}: {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-2 mt-6">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage <= 1}
      >
        <ChevronLeft className="h-4 w-4" />
        Previous
      </Button>
      <span className="text-sm text-muted-foreground px-4">
        Page {currentPage} of {totalPages}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage >= totalPages}
      >
        Next
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function RunsPageSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-16 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-9 w-full rounded-md" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-[260px] rounded-lg" />
        <Skeleton className="h-[260px] rounded-lg" />
      </div>
      <Skeleton className="h-[400px] rounded-lg" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Activity className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No Runs Yet</CardTitle>
        <CardDescription className="max-w-sm">
          Analysis pipeline runs will appear here after running autonomous deep analysis.
          Each run tracks duration, cost, token usage, and per-phase breakdowns.
        </CardDescription>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

export default function RunsPage() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');

  // Build query params
  const queryParams = useMemo(() => {
    const params: { page: number; page_size: number; status?: string; search?: string } = {
      page,
      page_size: PAGE_SIZE,
    };
    if (statusFilter !== 'all') params.status = statusFilter;
    if (search.trim()) params.search = search.trim();
    return params;
  }, [page, statusFilter, search]);

  const { data: runsData, isLoading: runsLoading, error: runsError } = useRuns(queryParams);
  const { data: statsData, isLoading: statsLoading } = useRunsStats();

  // Separate query for charts: fetch ALL runs (up to 1000) without filters
  const { data: allRunsData } = useRuns({ page: 1, page_size: 1000 });

  const runs = runsData?.runs ?? [];
  const allRuns = allRunsData?.runs ?? [];
  const totalRuns = runsData?.total ?? 0;
  const totalPages = Math.ceil(totalRuns / PAGE_SIZE);

  // Reset page when filters change
  const handleStatusChange = useCallback((v: string) => {
    setStatusFilter(v);
    setPage(1);
  }, []);

  const handleSearchChange = useCallback((v: string) => {
    setSearch(v);
    setPage(1);
  }, []);

  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <Activity className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Past Runs</h1>
        </div>
        <p className="text-muted-foreground mt-1">
          Analysis pipeline execution history
        </p>
      </div>

      {/* Content */}
      {runsLoading && !runsData ? (
        <RunsPageSkeleton />
      ) : runsError ? (
        <ConnectionError error={runsError} />
      ) : runs.length === 0 && statusFilter === 'all' && !search ? (
        <EmptyState />
      ) : (
        <>
          {/* Stat Cards */}
          <StatsCards
            totalRuns={statsData?.completed_runs ?? 0}
            totalCost={statsData?.total_cost_usd ?? 0}
            avgDuration={statsData?.avg_duration_seconds ?? null}
            totalTokens={(statsData?.total_input_tokens ?? 0) + (statsData?.total_output_tokens ?? 0)}
            isLoading={statsLoading}
          />

          {/* Filter Bar */}
          <FilterBar
            statusFilter={statusFilter}
            onStatusChange={handleStatusChange}
            search={search}
            onSearchChange={handleSearchChange}
          />

          {/* Results count */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              Showing {runs.length} of {totalRuns} runs
            </span>
          </div>

          {/* Charts — use ALL runs, not just the current page */}
          {allRuns.length > 0 && (
            <div className="grid gap-4 md:grid-cols-2">
              <DurationChart runs={allRuns} />
              <CostChart runs={allRuns} />
            </div>
          )}

          {/* Runs Table */}
          <RunsTable runs={runs} />

          {/* Pagination */}
          <Pagination
            currentPage={page}
            totalPages={totalPages}
            onPageChange={handlePageChange}
          />
        </>
      )}
    </div>
  );
}
