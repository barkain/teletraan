'use client';

import { useState, useMemo, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
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
import { useReportList } from '@/lib/hooks/use-reports';
import type { ReportSummary } from '@/lib/types/report';
import {
  FileText,
  Search,
  LayoutGrid,
  List,
  Calendar,
  ExternalLink,
  BarChart3,
  Lightbulb,
  Target,
  Clock,
  X,
  ArrowUpDown,
  ChevronUp,
  ChevronDown,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'Unknown date';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

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

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return 'N/A';
  const now = new Date();
  const then = new Date(dateStr);
  const diffMs = now.getTime() - then.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return `${Math.floor(diffDays / 7)}w ago`;
}

function getMonthKey(dateStr: string | null): string {
  if (!dateStr) return 'Unknown';
  const d = new Date(dateStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function formatMonthLabel(key: string): string {
  if (key === 'Unknown') return 'Unknown Date';
  const [year, month] = key.split('-');
  const d = new Date(Number(year), Number(month) - 1, 1);
  return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

function normalizeRegime(regime: string | null): string {
  if (!regime) return 'unknown';
  const lower = regime.toLowerCase();
  if (lower.includes('bullish') || lower.includes('risk-on')) return 'bullish';
  if (lower.includes('bearish') || lower.includes('risk-off')) return 'bearish';
  if (lower.includes('transition')) return 'transitional';
  if (lower.includes('volatile') || lower.includes('neutral')) return 'neutral';
  return 'unknown';
}

const REGIME_BADGE_COLORS: Record<string, string> = {
  bullish: 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-300',
  bearish: 'bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-300',
  transitional: 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-300',
  neutral: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/60 dark:text-yellow-300',
  unknown: 'bg-muted text-muted-foreground',
};

const REGIME_BORDER_COLORS: Record<string, string> = {
  bullish: 'border-l-green-500',
  bearish: 'border-l-red-500',
  transitional: 'border-l-amber-500',
  neutral: 'border-l-yellow-500',
  unknown: 'border-l-muted-foreground/30',
};

function getRegimeBadgeColor(regime: string | null): string {
  return REGIME_BADGE_COLORS[normalizeRegime(regime)] ?? REGIME_BADGE_COLORS.unknown;
}

function getRegimeBorderColor(regime: string | null): string {
  return REGIME_BORDER_COLORS[normalizeRegime(regime)] ?? REGIME_BORDER_COLORS.unknown;
}

function isWithinDays(dateStr: string | null, days: number): boolean {
  if (!dateStr) return false;
  const d = new Date(dateStr);
  const now = new Date();
  return now.getTime() - d.getTime() <= days * 24 * 60 * 60 * 1000;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

// ---------------------------------------------------------------------------
// Action colors
// ---------------------------------------------------------------------------

const ACTION_COLORS: Record<string, string> = {
  buy: 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-300',
  sell: 'bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-300',
  watch: 'bg-blue-100 text-blue-800 dark:bg-blue-900/60 dark:text-blue-300',
  hold: 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-300',
  avoid: 'bg-orange-100 text-orange-800 dark:bg-orange-900/60 dark:text-orange-300',
};

function getActionColor(action: string): string {
  return ACTION_COLORS[action.toLowerCase()] ?? 'bg-muted text-muted-foreground';
}

// ---------------------------------------------------------------------------
// Date range filter
// ---------------------------------------------------------------------------

type DateRange = 'all' | 'week' | 'month' | '3months';

const DATE_RANGE_LABELS: Record<DateRange, string> = {
  all: 'All Time',
  week: 'This Week',
  month: 'This Month',
  '3months': 'Last 3 Months',
};

function matchesDateRange(dateStr: string | null, range: DateRange): boolean {
  if (range === 'all') return true;
  if (!dateStr) return false;
  switch (range) {
    case 'week':
      return isWithinDays(dateStr, 7);
    case 'month':
      return isWithinDays(dateStr, 30);
    case '3months':
      return isWithinDays(dateStr, 90);
    default:
      return true;
  }
}

// ---------------------------------------------------------------------------
// Sort helpers for list view
// ---------------------------------------------------------------------------

type SortField = 'date' | 'regime' | 'confidence' | 'insights';
type SortDir = 'asc' | 'desc';

function compareReports(a: ReportSummary, b: ReportSummary, field: SortField, dir: SortDir): number {
  let cmp = 0;
  switch (field) {
    case 'date': {
      const da = a.completed_at ?? a.started_at ?? '';
      const db = b.completed_at ?? b.started_at ?? '';
      cmp = da.localeCompare(db);
      break;
    }
    case 'regime':
      cmp = (a.market_regime ?? '').localeCompare(b.market_regime ?? '');
      break;
    case 'confidence':
      cmp = (a.avg_confidence ?? 0) - (b.avg_confidence ?? 0);
      break;
    case 'insights':
      cmp = a.insights_count - b.insights_count;
      break;
  }
  return dir === 'asc' ? cmp : -cmp;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatsBar({ reports }: { reports: ReportSummary[] }) {
  const stats = useMemo(() => {
    const totalInsights = reports.reduce((acc, r) => acc + r.insights_count, 0);
    const confidences = reports.map((r) => r.avg_confidence).filter((c) => c > 0);
    const avgConfidence =
      confidences.length > 0
        ? Math.round(confidences.reduce((a, b) => a + b, 0) / confidences.length)
        : 0;
    const latestDate =
      reports.length > 0 ? (reports[0].completed_at ?? reports[0].started_at) : null;
    return { totalReports: reports.length, totalInsights, avgConfidence, latestDate };
  }, [reports]);

  const statItems = [
    { icon: BarChart3, label: `${stats.totalReports} Reports` },
    { icon: Lightbulb, label: `${stats.totalInsights} Insights` },
    { icon: Target, label: `Avg ${stats.avgConfidence}% Confidence` },
    { icon: Clock, label: `Latest: ${timeAgo(stats.latestDate)}` },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {statItems.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-3 px-4 py-3 rounded-lg bg-card/80 backdrop-blur-sm border border-border/50"
        >
          <item.icon className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm font-medium truncate">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

function FilterBar({
  search,
  onSearchChange,
  regime,
  onRegimeChange,
  dateRange,
  onDateRangeChange,
  regimeOptions,
  filteredCount,
  totalCount,
  activeFilterCount,
  onClearFilters,
}: {
  search: string;
  onSearchChange: (v: string) => void;
  regime: string;
  onRegimeChange: (v: string) => void;
  dateRange: DateRange;
  onDateRangeChange: (v: DateRange) => void;
  regimeOptions: string[];
  filteredCount: number;
  totalCount: number;
  activeFilterCount: number;
  onClearFilters: () => void;
}) {
  return (
    <div className="flex flex-col md:flex-row gap-3 items-start md:items-center">
      {/* Search */}
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search reports..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Regime dropdown */}
      <Select value={regime} onValueChange={onRegimeChange}>
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="All Regimes" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Regimes</SelectItem>
          {regimeOptions.map((r) => (
            <SelectItem key={r} value={r}>
              {r}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Date range */}
      <Select value={dateRange} onValueChange={(v) => onDateRangeChange(v as DateRange)}>
        <SelectTrigger className="w-[150px]">
          <Calendar className="h-4 w-4 mr-1" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(DATE_RANGE_LABELS).map(([key, label]) => (
            <SelectItem key={key} value={key}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Active filters + clear */}
      {activeFilterCount > 0 && (
        <Button variant="ghost" size="sm" onClick={onClearFilters} className="gap-1">
          <X className="h-3 w-3" />
          Clear ({activeFilterCount})
        </Button>
      )}

      {/* Count */}
      <span className="text-sm text-muted-foreground whitespace-nowrap ml-auto">
        Showing {filteredCount} of {totalCount} reports
      </span>
    </div>
  );
}

function ReportCard({
  report,
  isLatest,
  onClick,
}: {
  report: ReportSummary;
  isLatest: boolean;
  onClick: () => void;
}) {
  const MAX_SYMBOLS = 5;
  const symbols = report.symbols ?? [];
  const extraSymbols = symbols.length > MAX_SYMBOLS ? symbols.length - MAX_SYMBOLS : 0;
  const displayedSymbols = symbols.slice(0, MAX_SYMBOLS);

  const actions = Object.entries(report.action_summary ?? {});
  const confidence = Math.round(report.avg_confidence ?? 0);

  return (
    <Card
      className={`cursor-pointer bg-card/80 backdrop-blur-sm border border-border/50 border-l-4 ${getRegimeBorderColor(report.market_regime)} hover:scale-[1.01] hover:shadow-lg transition-all duration-200`}
      onClick={onClick}
    >
      <CardContent className="p-4 space-y-3">
        {/* Zone 1 - Header: date + regime + latest badge */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">
              {formatDate(report.completed_at ?? report.started_at)}
            </span>
            {isLatest && (
              <Badge
                variant="secondary"
                className="text-[10px] px-1.5 py-0 bg-primary/10 text-primary font-semibold uppercase tracking-wider"
              >
                Latest
              </Badge>
            )}
          </div>
          {report.market_regime && (
            <Badge
              variant="secondary"
              className={`text-xs shrink-0 ${getRegimeBadgeColor(report.market_regime)}`}
            >
              {report.market_regime}
            </Badge>
          )}
        </div>

        {/* Zone 2 - Symbols */}
        {displayedSymbols.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {displayedSymbols.map((sym) => (
              <span key={sym} className="font-mono text-xs px-2 py-0.5 rounded bg-muted">
                {sym}
              </span>
            ))}
            {extraSymbols > 0 && (
              <span className="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground">
                +{extraSymbols} more
              </span>
            )}
          </div>
        )}

        {/* Zone 3 - Actions & Confidence */}
        <div className="flex items-center gap-3">
          <div className="flex flex-wrap gap-1">
            {actions.map(([action, count]) => (
              <Badge
                key={action}
                variant="secondary"
                className={`text-[11px] px-1.5 py-0 ${getActionColor(action)}`}
              >
                {count} {capitalize(action)}
              </Badge>
            ))}
          </div>
          {confidence > 0 && (
            <div className="flex items-center gap-2 ml-auto min-w-[80px]">
              <Progress value={confidence} className="h-1.5 flex-1" />
              <span className="text-xs text-muted-foreground font-mono">{confidence}%</span>
            </div>
          )}
        </div>

        {/* Zone 4 - Footer: summary + insight count + published */}
        {report.discovery_summary && (
          <p className="text-sm text-muted-foreground line-clamp-2">
            {report.discovery_summary}
          </p>
        )}
        <div className="flex items-center justify-between pt-1">
          <span className="text-xs text-muted-foreground">
            {report.insights_count} insight{report.insights_count !== 1 ? 's' : ''}
          </span>
          {report.published_url && (
            <a
              href={report.published_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              Published
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function MonthGroupedGrid({
  reports,
  latestId,
  onCardClick,
}: {
  reports: ReportSummary[];
  latestId: string | null;
  onCardClick: (report: ReportSummary) => void;
}) {
  const groups = useMemo(() => {
    const map = new Map<string, ReportSummary[]>();
    for (const report of reports) {
      const key = getMonthKey(report.completed_at ?? report.started_at);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(report);
    }
    return Array.from(map.entries()).sort(([a], [b]) => b.localeCompare(a));
  }, [reports]);

  if (groups.length === 0) return <EmptyFilterState />;

  return (
    <div className="space-y-8">
      {groups.map(([monthKey, monthReports]) => {
        const totalInsights = monthReports.reduce((a, r) => a + r.insights_count, 0);
        return (
          <div key={monthKey}>
            {/* Month section header */}
            <div className="flex items-center gap-3 mb-4">
              <div className="h-px flex-1 bg-border" />
              <span className="text-sm font-semibold text-muted-foreground whitespace-nowrap">
                {formatMonthLabel(monthKey)} ({monthReports.length} report
                {monthReports.length !== 1 ? 's' : ''} &middot; {totalInsights} insight
                {totalInsights !== 1 ? 's' : ''})
              </span>
              <div className="h-px flex-1 bg-border" />
            </div>

            {/* Cards grid */}
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {monthReports.map((report) => (
                <ReportCard
                  key={report.id}
                  report={report}
                  isLatest={report.id === latestId}
                  onClick={() => onCardClick(report)}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function SortableHeader({
  label,
  field,
  sortField,
  sortDir,
  onSort,
}: {
  label: string;
  field: SortField;
  sortField: SortField;
  sortDir: SortDir;
  onSort: (f: SortField) => void;
}) {
  const isActive = sortField === field;
  return (
    <TableHead
      className="cursor-pointer select-none hover:text-foreground transition-colors"
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

function CompactListView({
  reports,
  latestId,
  onRowClick,
}: {
  reports: ReportSummary[];
  latestId: string | null;
  onRowClick: (report: ReportSummary) => void;
}) {
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

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
    () => [...reports].sort((a, b) => compareReports(a, b, sortField, sortDir)),
    [reports, sortField, sortDir],
  );

  if (sorted.length === 0) return <EmptyFilterState />;

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
            <SortableHeader
              label="Regime"
              field="regime"
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
            />
            <TableHead>Symbols</TableHead>
            <TableHead>Actions</TableHead>
            <SortableHeader
              label="Conf"
              field="confidence"
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
            />
            <TableHead>Published</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((report) => {
            const symbols = report.symbols ?? [];
            const maxSym = 3;
            const extra = symbols.length > maxSym ? symbols.length - maxSym : 0;
            const actions = Object.entries(report.action_summary ?? {});
            const confidence = Math.round(report.avg_confidence ?? 0);

            return (
              <TableRow
                key={report.id}
                className="cursor-pointer hover:bg-muted/50 transition-colors"
                onClick={() => onRowClick(report)}
              >
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    {formatShortDate(report.completed_at ?? report.started_at)}
                    {report.id === latestId && (
                      <Badge
                        variant="secondary"
                        className="text-[10px] px-1 py-0 bg-primary/10 text-primary font-semibold uppercase tracking-wider"
                      >
                        Latest
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  {report.market_regime ? (
                    <Badge
                      variant="secondary"
                      className={`text-xs ${getRegimeBadgeColor(report.market_regime)}`}
                    >
                      {report.market_regime}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">--</span>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    {symbols.slice(0, maxSym).map((s) => (
                      <span key={s} className="font-mono text-xs px-1.5 py-0.5 rounded bg-muted">
                        {s}
                      </span>
                    ))}
                    {extra > 0 && (
                      <span className="text-xs text-muted-foreground">+{extra}</span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    {actions.map(([action, count]) => (
                      <Badge
                        key={action}
                        variant="secondary"
                        className={`text-[11px] px-1 py-0 ${getActionColor(action)}`}
                      >
                        {count} {capitalize(action)}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  {confidence > 0 ? (
                    <span className="font-mono text-sm">{confidence}%</span>
                  ) : (
                    <span className="text-muted-foreground">--</span>
                  )}
                </TableCell>
                <TableCell className="text-center">{report.insights_count}</TableCell>
                <TableCell className="text-center">
                  {report.published_url ? (
                    <a
                      href={report.published_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="text-primary hover:underline"
                    >
                      <ExternalLink className="h-3.5 w-3.5 inline" />
                    </a>
                  ) : (
                    <span className="text-muted-foreground">&mdash;</span>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty / Loading / Error states
// ---------------------------------------------------------------------------

function ReportsListSkeleton() {
  return (
    <div className="space-y-6">
      {/* Stats bar skeleton */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-12 rounded-lg" />
        ))}
      </div>
      {/* Filter bar skeleton */}
      <Skeleton className="h-9 w-full rounded-md" />
      {/* Cards skeleton */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-4 space-y-3">
              <div className="flex items-start justify-between">
                <Skeleton className="h-4 w-36" />
                <Skeleton className="h-5 w-20" />
              </div>
              <div className="flex gap-1">
                <Skeleton className="h-5 w-12" />
                <Skeleton className="h-5 w-12" />
                <Skeleton className="h-5 w-12" />
              </div>
              <div className="flex gap-1">
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-4 w-16" />
              </div>
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
              <div className="flex justify-between">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-16" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <FileText className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No Reports Yet</CardTitle>
        <CardDescription className="max-w-sm">
          Analysis reports will appear here after running autonomous deep analysis. Reports
          contain market regime assessment, sector rotation signals, and actionable investment
          insights.
        </CardDescription>
      </CardContent>
    </Card>
  );
}

function EmptyFilterState() {
  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Search className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No Matching Reports</CardTitle>
        <CardDescription className="max-w-sm">
          No reports match the current filters. Try adjusting your search or filter criteria.
        </CardDescription>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function ReportsPage() {
  const { data, isLoading, error } = useReportList({ limit: 200 });

  // View toggle
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');

  // Filter state
  const [search, setSearch] = useState('');
  const [regime, setRegime] = useState('all');
  const [dateRange, setDateRange] = useState<DateRange>('all');

  // All reports
  const allReports = data?.items ?? [];

  // Extract unique regimes
  const regimeOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of allReports) {
      if (r.market_regime) set.add(r.market_regime);
    }
    return Array.from(set).sort();
  }, [allReports]);

  // Filtered reports
  const filteredReports = useMemo(() => {
    return allReports.filter((r) => {
      // Search filter
      if (search) {
        const q = search.toLowerCase();
        const matchesSummary = r.discovery_summary?.toLowerCase().includes(q);
        const matchesSymbol = (r.symbols ?? []).some((s) => s.toLowerCase().includes(q));
        const matchesRegime = r.market_regime?.toLowerCase().includes(q);
        if (!matchesSummary && !matchesSymbol && !matchesRegime) return false;
      }
      // Regime filter
      if (regime !== 'all' && r.market_regime !== regime) return false;
      // Date range filter
      if (!matchesDateRange(r.completed_at ?? r.started_at, dateRange)) return false;
      return true;
    });
  }, [allReports, search, regime, dateRange]);

  // Active filter count
  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (search) count++;
    if (regime !== 'all') count++;
    if (dateRange !== 'all') count++;
    return count;
  }, [search, regime, dateRange]);

  // Latest report ID
  const latestId = allReports.length > 0 ? allReports[0].id : null;

  // Clear filters
  const handleClearFilters = useCallback(() => {
    setSearch('');
    setRegime('all');
    setDateRange('all');
  }, []);

  // Card/row click handler
  const handleReportClick = useCallback((report: ReportSummary) => {
    if (report.published_url) {
      window.open(report.published_url, '_blank', 'noopener,noreferrer');
    } else {
      window.location.href = `/reports/${report.id}`;
    }
  }, []);

  return (
    <div className="space-y-6">
      {/* 1. Page Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Analysis Reports</h1>
          <p className="text-muted-foreground mt-1">AI-powered market intelligence reports</p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-border/50 p-1 bg-card/80 backdrop-blur-sm">
          <Button
            variant={viewMode === 'grid' ? 'secondary' : 'ghost'}
            size="icon-sm"
            onClick={() => setViewMode('grid')}
            aria-label="Grid view"
          >
            <LayoutGrid className="h-4 w-4" />
          </Button>
          <Button
            variant={viewMode === 'list' ? 'secondary' : 'ghost'}
            size="icon-sm"
            onClick={() => setViewMode('list')}
            aria-label="List view"
          >
            <List className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <ReportsListSkeleton />
      ) : error ? (
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <CardTitle className="text-lg mb-2 text-destructive">
              Error Loading Reports
            </CardTitle>
            <CardDescription>
              {error instanceof Error ? error.message : 'An unexpected error occurred'}
            </CardDescription>
          </CardContent>
        </Card>
      ) : allReports.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          {/* 2. Stats Bar */}
          <StatsBar reports={allReports} />

          {/* 3. Filter Bar */}
          <FilterBar
            search={search}
            onSearchChange={setSearch}
            regime={regime}
            onRegimeChange={setRegime}
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
            regimeOptions={regimeOptions}
            filteredCount={filteredReports.length}
            totalCount={allReports.length}
            activeFilterCount={activeFilterCount}
            onClearFilters={handleClearFilters}
          />

          {/* 4/5/6. Grid or List view */}
          {viewMode === 'grid' ? (
            <MonthGroupedGrid
              reports={filteredReports}
              latestId={latestId}
              onCardClick={handleReportClick}
            />
          ) : (
            <CompactListView
              reports={filteredReports}
              latestId={latestId}
              onRowClick={handleReportClick}
            />
          )}
        </>
      )}
    </div>
  );
}
