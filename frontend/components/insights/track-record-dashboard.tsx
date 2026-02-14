'use client';

import * as React from 'react';
import Link from 'next/link';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  Legend,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import {
  useTrackRecord,
  useOutcomeSummary,
  useOutcomes,
  useMonthlyTrend,
} from '@/lib/hooks/use-track-record';
import type {
  OutcomeCategory,
  InsightOutcome,
  TrackRecordStats,
  OutcomeSummary,
} from '@/lib/types/track-record';
import { Progress } from '@/components/ui/progress';
import {
  BarChart3,
  Target,
  Activity,
  Clock,
  TrendingUp,
  TrendingDown,
  Download,
  ChevronUp,
  ChevronDown,
  ExternalLink,
  ArrowUpDown,
  Eye,
} from 'lucide-react';

// ============================================
// Types & Constants
// ============================================

interface TrackRecordDashboardProps {
  lookbackDays?: number;
  insightType?: string;
  actionType?: string;
  className?: string;
}

type TimePeriod = '30' | '60' | '90' | '180' | 'all';

type SortField = 'name' | 'total' | 'successful' | 'rate' | 'avgReturn';
type SortDirection = 'asc' | 'desc';

const TIME_PERIODS: { value: TimePeriod; label: string }[] = [
  { value: '30', label: '30d' },
  { value: '60', label: '60d' },
  { value: '90', label: '90d' },
  { value: '180', label: '180d' },
  { value: 'all', label: 'All' },
];

const OUTCOME_COLORS: Record<OutcomeCategory, string> = {
  STRONG_SUCCESS: '#22c55e',
  SUCCESS: '#4ade80',
  PARTIAL_SUCCESS: '#86efac',
  NEUTRAL: '#9ca3af',
  PARTIAL_FAILURE: '#fca5a5',
  FAILURE: '#f87171',
  STRONG_FAILURE: '#ef4444',
};

const ACTION_COLORS: Record<string, string> = {
  BUY: '#22c55e',
  SELL: '#ef4444',
  HOLD: '#3b82f6',
};

// ============================================
// Utility Functions
// ============================================

function formatPercent(value: number | undefined | null): string {
  if (value === undefined || value === null) return 'N/A';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

function formatSuccessRate(value: number | undefined | null): string {
  if (value === undefined || value === null) return 'N/A';
  return `${(value * 100).toFixed(1)}%`;
}

function getOutcomeBadgeVariant(category: OutcomeCategory): 'default' | 'secondary' | 'destructive' {
  if (category.includes('SUCCESS')) return 'default';
  if (category.includes('FAILURE')) return 'destructive';
  return 'secondary';
}

function getOutcomeLabel(category: OutcomeCategory): string {
  return category
    .split('_')
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(' ');
}

// ============================================
// Skeleton Components
// ============================================

function StatCardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-4" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-16 mb-1" />
        <Skeleton className="h-3 w-20" />
      </CardContent>
    </Card>
  );
}

function ChartSkeleton({ height = 200 }: { height?: number }) {
  return (
    <div className="w-full" style={{ height }}>
      <Skeleton className="h-full w-full rounded-lg" />
    </div>
  );
}

// ============================================
// Stat Card Component
// ============================================

interface StatCardProps {
  title: string;
  value: string | number;
  description?: string;
  icon: React.ReactNode;
  trend?: number;
  trendLabel?: string;
}

function StatCard({ title, value, description, icon, trend, trendLabel }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <div className="h-4 w-4 text-muted-foreground">{icon}</div>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <div className="text-2xl font-bold">{value}</div>
          {trend !== undefined && (
            <div
              className={cn(
                'flex items-center text-xs font-medium',
                trend >= 0 ? 'text-green-600' : 'text-red-600'
              )}
            >
              {trend >= 0 ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
              {Math.abs(trend).toFixed(1)}%
              {trendLabel && <span className="ml-1 text-muted-foreground">{trendLabel}</span>}
            </div>
          )}
        </div>
        {description && (
          <p className="text-xs text-muted-foreground mt-1">{description}</p>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================
// Chart Components
// ============================================

interface TypeBreakdownChartProps {
  data: TrackRecordStats['by_type'];
}

function TypeBreakdownChart({ data }: TypeBreakdownChartProps) {
  const chartData = React.useMemo(() => {
    return Object.entries(data).map(([type, stats]) => ({
      name: type.charAt(0).toUpperCase() + type.slice(1).toLowerCase(),
      rate: stats.success_rate * 100,
      total: stats.total,
      successful: stats.successful,
    }));
  }, [data]);

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-muted-foreground">
        No data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={chartData} layout="vertical" margin={{ left: 20 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
        <YAxis dataKey="name" type="category" width={80} tick={{ fontSize: 12 }} />
        <RechartsTooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const item = payload[0].payload;
            return (
              <div className="bg-popover border border-border rounded-lg shadow-lg p-3">
                <p className="font-semibold">{item.name}</p>
                <p className="text-sm">Success Rate: {item.rate.toFixed(1)}%</p>
                <p className="text-sm text-muted-foreground">
                  {item.successful} of {item.total} insights
                </p>
              </div>
            );
          }}
        />
        <Bar dataKey="rate" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

interface ActionPieChartProps {
  data: OutcomeSummary['by_direction'];
}

function ActionPieChart({ data }: ActionPieChartProps) {
  const chartData = React.useMemo(() => {
    return Object.entries(data).map(([action, stats]) => ({
      name: action,
      value: stats.total,
      correct: stats.correct,
      avgReturn: stats.avg_return,
    }));
  }, [data]);

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-muted-foreground">
        No data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie
          data={chartData}
          cx="50%"
          cy="50%"
          innerRadius={40}
          outerRadius={70}
          paddingAngle={2}
          dataKey="value"
          label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
          labelLine={false}
        >
          {chartData.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={ACTION_COLORS[entry.name] || '#8884d8'} />
          ))}
        </Pie>
        <RechartsTooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const item = payload[0].payload;
            return (
              <div className="bg-popover border border-border rounded-lg shadow-lg p-3">
                <p className="font-semibold">{item.name}</p>
                <p className="text-sm">Total: {item.value}</p>
                <p className="text-sm">Correct: {item.correct}</p>
                <p className="text-sm">Avg Return: {formatPercent(item.avgReturn)}</p>
              </div>
            );
          }}
        />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  );
}

interface OutcomeCategoryChartProps {
  data: OutcomeSummary['by_category'];
}

function OutcomeCategoryChart({ data }: OutcomeCategoryChartProps) {
  const chartData = React.useMemo(() => {
    const categories: OutcomeCategory[] = [
      'STRONG_SUCCESS',
      'SUCCESS',
      'PARTIAL_SUCCESS',
      'NEUTRAL',
      'PARTIAL_FAILURE',
      'FAILURE',
      'STRONG_FAILURE',
    ];
    return categories.map((cat) => ({
      name: getOutcomeLabel(cat),
      value: data[cat] || 0,
      color: OUTCOME_COLORS[cat],
    }));
  }, [data]);

  const hasData = chartData.some((d) => d.value > 0);

  if (!hasData) {
    return (
      <div className="flex items-center justify-center h-[200px] text-muted-foreground">
        No data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={chartData} margin={{ bottom: 60 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 10 }}
          angle={-45}
          textAnchor="end"
          interval={0}
        />
        <YAxis />
        <RechartsTooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const item = payload[0].payload;
            return (
              <div className="bg-popover border border-border rounded-lg shadow-lg p-3">
                <p className="font-semibold">{item.name}</p>
                <p className="text-sm">Count: {item.value}</p>
              </div>
            );
          }}
        />
        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
          {chartData.map((entry, index) => (
            <Cell key={`cell-${index}`} fill={entry.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

interface MonthlyTrendChartProps {
  isLoading?: boolean;
}

function MonthlyTrendChart({ isLoading: parentLoading }: MonthlyTrendChartProps) {
  const { data, isLoading, isError } = useMonthlyTrend({ lookback_months: 6 });

  if (parentLoading || isLoading) {
    return <ChartSkeleton />;
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center h-[200px] text-muted-foreground">
        No trend data available yet
      </div>
    );
  }

  if (!data?.data || data.data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-muted-foreground">
        No trend data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data.data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="month" />
        <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
        <RechartsTooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const item = payload[0].payload;
            return (
              <div className="bg-popover border border-border rounded-lg shadow-lg p-3">
                <p className="font-semibold">{item.month}</p>
                <p className="text-sm">Success Rate: {item.rate}%</p>
                {item.total !== undefined && (
                  <p className="text-xs text-muted-foreground">
                    {item.successful ?? 0} of {item.total} insights
                  </p>
                )}
              </div>
            );
          }}
        />
        <Line
          type="monotone"
          dataKey="rate"
          stroke="hsl(var(--primary))"
          strokeWidth={2}
          dot={{ fill: 'hsl(var(--primary))' }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ============================================
// Stats Table Component
// ============================================

function SortableHeader({
  field,
  sortField,
  sortDirection,
  onSort,
  children,
}: {
  field: SortField;
  sortField: SortField;
  sortDirection: SortDirection;
  onSort: (field: SortField) => void;
  children: React.ReactNode;
}) {
  return (
    <TableHead
      className="cursor-pointer hover:bg-muted/50 transition-colors"
      onClick={() => onSort(field)}
    >
      <div className="flex items-center gap-1">
        {children}
        {sortField === field ? (
          sortDirection === 'desc' ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronUp className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-30" />
        )}
      </div>
    </TableHead>
  );
}

interface StatsTableProps {
  byType: TrackRecordStats['by_type'];
  byAction: TrackRecordStats['by_action'];
  onRowClick?: (category: 'type' | 'action', name: string) => void;
}

function StatsTable({ byType, byAction, onRowClick }: StatsTableProps) {
  const [sortField, setSortField] = React.useState<SortField>('rate');
  const [sortDirection, setSortDirection] = React.useState<SortDirection>('desc');

  const tableData = React.useMemo(() => {
    const rows = [
      ...Object.entries(byType).map(([name, stats]) => ({
        category: 'type' as const,
        name: name.charAt(0).toUpperCase() + name.slice(1).toLowerCase(),
        rawName: name,
        total: stats.total,
        successful: stats.successful,
        rate: stats.success_rate,
        avgReturn: 0, // Would come from extended API
      })),
      ...Object.entries(byAction).map(([name, stats]) => ({
        category: 'action' as const,
        name,
        rawName: name,
        total: stats.total,
        successful: stats.successful,
        rate: stats.success_rate,
        avgReturn: 0,
      })),
    ];

    return rows.sort((a, b) => {
      const multiplier = sortDirection === 'asc' ? 1 : -1;
      if (sortField === 'name') {
        return multiplier * a.name.localeCompare(b.name);
      }
      return multiplier * ((a[sortField] || 0) - (b[sortField] || 0));
    });
  }, [byType, byAction, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection('desc');
    }
  };

  if (tableData.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No statistics available
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <SortableHeader field="name" sortField={sortField} sortDirection={sortDirection} onSort={handleSort}>Type/Action</SortableHeader>
          <SortableHeader field="total" sortField={sortField} sortDirection={sortDirection} onSort={handleSort}>Total</SortableHeader>
          <SortableHeader field="successful" sortField={sortField} sortDirection={sortDirection} onSort={handleSort}>Successful</SortableHeader>
          <SortableHeader field="rate" sortField={sortField} sortDirection={sortDirection} onSort={handleSort}>Rate</SortableHeader>
          <SortableHeader field="avgReturn" sortField={sortField} sortDirection={sortDirection} onSort={handleSort}>Avg Return</SortableHeader>
        </TableRow>
      </TableHeader>
      <TableBody>
        {tableData.map((row) => (
          <TableRow
            key={`${row.category}-${row.rawName}`}
            className={cn(onRowClick && 'cursor-pointer')}
            onClick={() => onRowClick?.(row.category, row.rawName)}
          >
            <TableCell>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-xs capitalize">
                  {row.category}
                </Badge>
                {row.name}
              </div>
            </TableCell>
            <TableCell>{row.total}</TableCell>
            <TableCell>{row.successful}</TableCell>
            <TableCell
              className={cn(
                row.rate >= 0.6
                  ? 'text-green-600'
                  : row.rate >= 0.4
                  ? 'text-yellow-600'
                  : 'text-red-600'
              )}
            >
              {formatSuccessRate(row.rate)}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {formatPercent(row.avgReturn)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// ============================================
// Recent Outcomes List Component
// ============================================

interface RecentOutcomesListProps {
  outcomes: InsightOutcome[];
  isLoading: boolean;
}

function RecentOutcomesList({ outcomes, isLoading }: RecentOutcomesListProps) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
    );
  }

  if (outcomes.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No completed outcomes yet
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {outcomes.slice(0, 10).map((outcome) => {
        const isSuccess = outcome.outcome_category?.includes('SUCCESS');
        const isFailure = outcome.outcome_category?.includes('FAILURE');

        return (
          <Card
            key={outcome.id}
            className={cn(
              'transition-all hover:shadow-md',
              isSuccess && 'border-l-4 border-l-green-500',
              isFailure && 'border-l-4 border-l-red-500'
            )}
          >
            <CardContent className="py-3">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {outcome.outcome_category && (
                      <Badge variant={getOutcomeBadgeVariant(outcome.outcome_category)}>
                        {getOutcomeLabel(outcome.outcome_category)}
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground">
                      {outcome.predicted_direction}
                    </span>
                  </div>
                  <p className="text-sm font-medium truncate">
                    Insight #{outcome.insight_id}
                  </p>
                  <div className="flex items-center gap-4 mt-1 text-xs text-muted-foreground">
                    <span>Entry: ${outcome.initial_price.toFixed(2)}</span>
                    {outcome.final_price && (
                      <span>Exit: ${outcome.final_price.toFixed(2)}</span>
                    )}
                    {outcome.days_remaining !== undefined && outcome.days_remaining > 0 && (
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {outcome.days_remaining}d left
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span
                    className={cn(
                      'text-lg font-bold',
                      (outcome.actual_return_pct ?? 0) >= 0
                        ? 'text-green-600'
                        : 'text-red-600'
                    )}
                  >
                    {formatPercent(outcome.actual_return_pct)}
                  </span>
                  <Link
                    href={`/insights/${outcome.insight_id}`}
                    className="text-xs text-primary hover:underline flex items-center gap-1"
                  >
                    View <ExternalLink className="h-3 w-3" />
                  </Link>
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

// ============================================
// Active Predictions Components
// ============================================

type ActiveSortField = 'symbol' | 'unrealized' | 'daysRemaining' | 'direction';
type ActiveSortDir = 'asc' | 'desc';

interface ActivePredictionsListProps {
  outcomes: InsightOutcome[];
  isLoading: boolean;
}

function ActiveSortableHeader({
  field,
  sortField,
  sortDir,
  onSort,
  children,
}: {
  field: ActiveSortField;
  sortField: ActiveSortField;
  sortDir: ActiveSortDir;
  onSort: (field: ActiveSortField) => void;
  children: React.ReactNode;
}) {
  return (
    <TableHead
      className="cursor-pointer hover:bg-muted/50 transition-colors"
      onClick={() => onSort(field)}
    >
      <div className="flex items-center gap-1">
        {children}
        {sortField === field ? (
          sortDir === 'desc' ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronUp className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-30" />
        )}
      </div>
    </TableHead>
  );
}

function ActivePredictionsList({ outcomes, isLoading }: ActivePredictionsListProps) {
  const [sortField, setSortField] = React.useState<ActiveSortField>('unrealized');
  const [sortDir, setSortDir] = React.useState<ActiveSortDir>('desc');

  const sorted = React.useMemo(() => {
    return [...outcomes].sort((a, b) => {
      const mul = sortDir === 'asc' ? 1 : -1;
      switch (sortField) {
        case 'symbol':
          return mul * (a.symbol ?? '').localeCompare(b.symbol ?? '');
        case 'unrealized':
          return mul * ((a.unrealized_return_pct ?? 0) - (b.unrealized_return_pct ?? 0));
        case 'daysRemaining':
          return mul * ((a.days_remaining ?? 0) - (b.days_remaining ?? 0));
        case 'direction':
          return mul * (a.predicted_direction ?? '').localeCompare(b.predicted_direction ?? '');
        default:
          return 0;
      }
    });
  }, [outcomes, sortField, sortDir]);

  const handleSort = (field: ActiveSortField) => {
    if (sortField === field) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir(field === 'symbol' ? 'asc' : 'desc');
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (outcomes.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        No active predictions being tracked
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <ActiveSortableHeader field="symbol" sortField={sortField} sortDir={sortDir} onSort={handleSort}>Symbol</ActiveSortableHeader>
            <ActiveSortableHeader field="direction" sortField={sortField} sortDir={sortDir} onSort={handleSort}>Direction</ActiveSortableHeader>
            <TableHead>Entry Price</TableHead>
            <TableHead>Current Price</TableHead>
            <ActiveSortableHeader field="unrealized" sortField={sortField} sortDir={sortDir} onSort={handleSort}>Unrealized</ActiveSortableHeader>
            <ActiveSortableHeader field="daysRemaining" sortField={sortField} sortDir={sortDir} onSort={handleSort}>Time Left</ActiveSortableHeader>
            <TableHead className="w-[140px]">Progress</TableHead>
            <TableHead className="w-[40px]"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((outcome) => {
            const unrealized = outcome.unrealized_return_pct ?? 0;
            const totalDays =
              outcome.tracking_start_date && outcome.tracking_end_date
                ? Math.max(
                    1,
                    (new Date(outcome.tracking_end_date).getTime() -
                      new Date(outcome.tracking_start_date).getTime()) /
                      (1000 * 60 * 60 * 24)
                  )
                : 28;
            const elapsed = totalDays - (outcome.days_remaining ?? 0);
            const progressPct = Math.min(100, Math.max(0, (elapsed / totalDays) * 100));

            // Determine if the current move aligns with predicted direction
            const isAligned =
              (outcome.predicted_direction === 'bullish' && unrealized > 0) ||
              (outcome.predicted_direction === 'bearish' && unrealized < 0) ||
              (outcome.predicted_direction === 'neutral' && Math.abs(unrealized) < 1);

            return (
              <TableRow key={outcome.id} className="group">
                <TableCell>
                  <div className="flex flex-col">
                    <span className="font-semibold text-sm">{outcome.symbol ?? '---'}</span>
                    <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                      {outcome.insight_title ?? `Insight #${outcome.insight_id}`}
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1.5">
                    <Badge
                      variant={
                        outcome.predicted_direction === 'bullish'
                          ? 'default'
                          : outcome.predicted_direction === 'bearish'
                          ? 'destructive'
                          : 'secondary'
                      }
                      className="text-xs capitalize"
                    >
                      {outcome.insight_action ?? outcome.predicted_direction}
                    </Badge>
                    {outcome.predicted_direction === 'bullish' ? (
                      <TrendingUp className="h-3 w-3 text-green-500" />
                    ) : outcome.predicted_direction === 'bearish' ? (
                      <TrendingDown className="h-3 w-3 text-red-500" />
                    ) : null}
                  </div>
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  ${outcome.initial_price.toFixed(2)}
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {outcome.current_price != null
                    ? `$${outcome.current_price.toFixed(2)}`
                    : '---'}
                </TableCell>
                <TableCell>
                  <span
                    className={cn(
                      'text-sm font-semibold tabular-nums',
                      isAligned ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                    )}
                  >
                    {unrealized >= 0 ? '+' : ''}
                    {unrealized.toFixed(2)}%
                  </span>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1 text-sm text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    <span>{outcome.days_remaining ?? 0}d</span>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Progress value={progressPct} className="h-2 flex-1" />
                    <span className="text-xs text-muted-foreground w-[32px] text-right">
                      {Math.round(progressPct)}%
                    </span>
                  </div>
                </TableCell>
                <TableCell>
                  <Link
                    href={`/insights/${outcome.insight_id}`}
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />
                  </Link>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

interface ActivePredictionsSummaryProps {
  outcomes: InsightOutcome[];
}

function ActivePredictionsSummary({ outcomes }: ActivePredictionsSummaryProps) {
  const stats = React.useMemo(() => {
    const bullish = outcomes.filter((o) => o.predicted_direction === 'bullish');
    const bearish = outcomes.filter((o) => o.predicted_direction === 'bearish');
    const neutral = outcomes.filter((o) => o.predicted_direction === 'neutral');

    const aligned = outcomes.filter((o) => {
      const ret = o.unrealized_return_pct ?? 0;
      if (o.predicted_direction === 'bullish') return ret > 0;
      if (o.predicted_direction === 'bearish') return ret < 0;
      return Math.abs(ret) < 1;
    });

    const allReturns = outcomes
      .map((o) => o.unrealized_return_pct ?? 0)
      .filter((r) => r !== 0);
    const avgReturn = allReturns.length > 0
      ? allReturns.reduce((a, b) => a + b, 0) / allReturns.length
      : 0;

    return { bullish: bullish.length, bearish: bearish.length, neutral: neutral.length, aligned: aligned.length, total: outcomes.length, avgReturn };
  }, [outcomes]);

  const directionData = [
    { name: 'Bullish', value: stats.bullish, color: '#22c55e' },
    { name: 'Bearish', value: stats.bearish, color: '#ef4444' },
    { name: 'Neutral', value: stats.neutral, color: '#3b82f6' },
  ].filter((d) => d.value > 0);

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Direction Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          {directionData.length === 0 ? (
            <div className="flex items-center justify-center h-[120px] text-muted-foreground text-sm">
              No data
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={120}>
              <PieChart>
                <Pie
                  data={directionData}
                  cx="50%"
                  cy="50%"
                  innerRadius={30}
                  outerRadius={50}
                  paddingAngle={2}
                  dataKey="value"
                  label={({ name, value }) => `${name} (${value})`}
                  labelLine={false}
                >
                  {directionData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <RechartsTooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const item = payload[0].payload;
                    return (
                      <div className="bg-popover border border-border rounded-lg shadow-lg p-2 text-sm">
                        <p className="font-semibold">{item.name}: {item.value}</p>
                      </div>
                    );
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Tracking Alignment</CardTitle>
          <CardDescription className="text-xs">Predictions moving in predicted direction</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-[120px] gap-2">
            <div className="text-3xl font-bold">
              {stats.total > 0 ? `${((stats.aligned / stats.total) * 100).toFixed(0)}%` : 'N/A'}
            </div>
            <p className="text-xs text-muted-foreground">
              {stats.aligned} of {stats.total} predictions on track
            </p>
            <Progress
              value={stats.total > 0 ? (stats.aligned / stats.total) * 100 : 0}
              className="h-2 w-full max-w-[200px]"
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Avg Unrealized Return</CardTitle>
          <CardDescription className="text-xs">Across all active predictions</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center h-[120px] gap-2">
            <div
              className={cn(
                'text-3xl font-bold',
                stats.avgReturn >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
              )}
            >
              {stats.avgReturn >= 0 ? '+' : ''}
              {stats.avgReturn.toFixed(2)}%
            </div>
            <p className="text-xs text-muted-foreground">
              Unrealized P&L across {stats.total} predictions
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ============================================
// Main Component
// ============================================

export function TrackRecordDashboard({
  lookbackDays = 90,
  insightType,
  actionType,
  className,
}: TrackRecordDashboardProps) {
  const [selectedPeriod, setSelectedPeriod] = React.useState<TimePeriod>(
    lookbackDays === 30 ? '30' : lookbackDays === 60 ? '60' : lookbackDays === 180 ? '180' : '90'
  );

  const periodDays = selectedPeriod === 'all' ? undefined : parseInt(selectedPeriod);

  // Fetch data
  const {
    data: trackRecord,
    isLoading: isLoadingTrackRecord,
  } = useTrackRecord({
    insight_type: insightType,
    action_type: actionType,
    lookback_days: periodDays,
  });

  const {
    data: outcomeSummary,
    isLoading: isLoadingSummary,
  } = useOutcomeSummary({
    insight_type: insightType,
    action_type: actionType,
    lookback_days: periodDays,
  });

  const {
    data: completedOutcomes,
    isLoading: isLoadingCompleted,
  } = useOutcomes({
    status: 'COMPLETED',
    limit: 10,
  });

  const {
    data: trackingOutcomes,
    isLoading: isLoadingTracking,
  } = useOutcomes({
    status: 'TRACKING',
    limit: 100,
  });

  const isLoading = isLoadingTrackRecord || isLoadingSummary;
  const hasCompleted = (outcomeSummary?.completed ?? 0) > 0;
  const activeItems = trackingOutcomes?.items ?? [];

  // Export handler
  const handleExport = React.useCallback(() => {
    if (!trackRecord) return;

    const headers = ['Category', 'Name', 'Total', 'Successful', 'Success Rate'];
    const rows = [
      ...Object.entries(trackRecord.by_type).map(([name, stats]) => [
        'Type',
        name,
        stats.total,
        stats.successful,
        `${(stats.success_rate * 100).toFixed(1)}%`,
      ]),
      ...Object.entries(trackRecord.by_action).map(([name, stats]) => [
        'Action',
        name,
        stats.total,
        stats.successful,
        `${(stats.success_rate * 100).toFixed(1)}%`,
      ]),
    ];

    const csv = [headers, ...rows].map((row) => row.join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `track-record-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [trackRecord]);

  return (
    <div className={cn('space-y-6', className)}>
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-6 w-6 text-primary" />
          <h2 className="text-2xl font-bold">Track Record</h2>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={selectedPeriod}
            onValueChange={(v) => setSelectedPeriod(v as TimePeriod)}
          >
            <SelectTrigger className="w-[100px]">
              <SelectValue placeholder="Period" />
            </SelectTrigger>
            <SelectContent>
              {TIME_PERIODS.map((period) => (
                <SelectItem key={period.value} value={period.value}>
                  {period.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="icon" onClick={handleExport} disabled={!trackRecord}>
            <Download className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Summary Stats Cards */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Overall Success Rate"
            value={hasCompleted ? formatSuccessRate(outcomeSummary?.success_rate ?? trackRecord?.success_rate) : 'Pending'}
            description={
              hasCompleted
                ? `${trackRecord?.successful ?? 0} of ${trackRecord?.total_insights ?? 0} successful`
                : 'Evaluations start when tracking periods end'
            }
            icon={<Target className="h-4 w-4" />}
          />
          <StatCard
            title="Total Predictions"
            value={outcomeSummary?.total_tracked ?? trackRecord?.total_insights ?? 0}
            description={hasCompleted ? 'Historical predictions' : 'Predictions being tracked'}
            icon={<Activity className="h-4 w-4" />}
          />
          <StatCard
            title="Currently Tracking"
            value={outcomeSummary?.currently_tracking ?? 0}
            description="Active predictions"
            icon={<Eye className="h-4 w-4" />}
          />
          <StatCard
            title={hasCompleted ? 'Avg Return (Correct)' : 'Completed'}
            value={
              hasCompleted
                ? formatPercent(outcomeSummary?.avg_return_when_correct ?? trackRecord?.avg_return_successful)
                : outcomeSummary?.completed ?? 0
            }
            description={
              hasCompleted
                ? `vs ${formatPercent(outcomeSummary?.avg_return_when_wrong ?? trackRecord?.avg_return_failed)} when wrong`
                : 'Outcomes evaluated so far'
            }
            icon={
              hasCompleted ? (
                (outcomeSummary?.avg_return_when_correct ?? 0) >= 0 ? (
                  <TrendingUp className="h-4 w-4" />
                ) : (
                  <TrendingDown className="h-4 w-4" />
                )
              ) : (
                <Clock className="h-4 w-4" />
              )
            }
          />
        </div>
      )}

      {/* Active Predictions Summary (shown when we have active tracking) */}
      {activeItems.length > 0 && !isLoadingTracking && (
        <ActivePredictionsSummary outcomes={activeItems} />
      )}

      {/* Active Predictions Table */}
      {(activeItems.length > 0 || isLoadingTracking) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Eye className="h-4 w-4" />
              Active Predictions
            </CardTitle>
            <CardDescription>
              {activeItems.length > 0
                ? `${activeItems.length} predictions being tracked -- outcomes evaluated when tracking periods end`
                : 'Loading active predictions...'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ActivePredictionsList
              outcomes={activeItems}
              isLoading={isLoadingTracking}
            />
          </CardContent>
        </Card>
      )}

      {/* Breakdown Charts -- only show if there are completed outcomes */}
      {hasCompleted && (
        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">By Insight Type</CardTitle>
              <CardDescription>Success rate breakdown by insight type</CardDescription>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <ChartSkeleton />
              ) : (
                <TypeBreakdownChart data={trackRecord?.by_type ?? {}} />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">By Action</CardTitle>
              <CardDescription>Distribution of BUY/SELL/HOLD actions</CardDescription>
            </CardHeader>
            <CardContent>
              {isLoadingSummary ? (
                <ChartSkeleton />
              ) : (
                <ActionPieChart data={outcomeSummary?.by_direction ?? {}} />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">By Outcome Category</CardTitle>
              <CardDescription>Distribution from strong success to strong failure</CardDescription>
            </CardHeader>
            <CardContent>
              {isLoadingSummary ? (
                <ChartSkeleton />
              ) : (
                <OutcomeCategoryChart
                  data={outcomeSummary?.by_category ?? ({} as OutcomeSummary['by_category'])}
                />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Monthly Trend</CardTitle>
              <CardDescription>Success rate over time</CardDescription>
            </CardHeader>
            <CardContent>
              <MonthlyTrendChart isLoading={isLoading} />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Stats Table -- only show if there are completed outcomes */}
      {hasCompleted && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Detailed Statistics</CardTitle>
            <CardDescription>Click column headers to sort</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : (
              <StatsTable
                byType={trackRecord?.by_type ?? {}}
                byAction={trackRecord?.by_action ?? {}}
              />
            )}
          </CardContent>
        </Card>
      )}

      {/* Recent Completed Outcomes -- only show if there are completed outcomes */}
      {hasCompleted && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent Completed Outcomes</CardTitle>
            <CardDescription>Last 10 validated predictions</CardDescription>
          </CardHeader>
          <CardContent>
            <RecentOutcomesList
              outcomes={completedOutcomes?.items ?? []}
              isLoading={isLoadingCompleted}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
