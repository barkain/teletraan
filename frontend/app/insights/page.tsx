'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { DeepInsightCard } from '@/components/insights/deep-insight-card';
import { StatisticalSignalsCard } from '@/components/insights/statistical-signals-card';
import { InsightDetailView } from '@/components/insights/insight-detail-view';
import { useDeepInsights, DeepInsightParams } from '@/lib/hooks/use-deep-insights';
import type { DeepInsight, DeepInsightType, InsightAction } from '@/types';
import { Sparkles, ChevronLeft, ChevronRight, Search, Filter, Activity, PanelRightOpen, Calendar, LayoutGrid, List, TrendingUp, TrendingDown, Minus, Target } from 'lucide-react';
import { ConnectionError } from '@/components/ui/empty-state';
import { cn } from '@/lib/utils';

const ITEMS_PER_PAGE = 10;

const actionOptions: { value: InsightAction | 'all'; label: string }[] = [
  { value: 'all', label: 'All Actions' },
  { value: 'STRONG_BUY', label: 'Strong Buy' },
  { value: 'BUY', label: 'Buy' },
  { value: 'HOLD', label: 'Hold' },
  { value: 'SELL', label: 'Sell' },
  { value: 'STRONG_SELL', label: 'Strong Sell' },
  { value: 'WATCH', label: 'Watch' },
];

const typeOptions: { value: DeepInsightType | 'all'; label: string }[] = [
  { value: 'all', label: 'All Types' },
  { value: 'opportunity', label: 'Opportunity' },
  { value: 'risk', label: 'Risk' },
  { value: 'rotation', label: 'Rotation' },
  { value: 'macro', label: 'Macro' },
  { value: 'divergence', label: 'Divergence' },
  { value: 'correlation', label: 'Correlation' },
];

function InsightsListSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <Skeleton className="h-6 w-24 mb-2" />
                <Skeleton className="h-5 w-3/4" />
                <div className="flex gap-1 mt-2">
                  <Skeleton className="h-5 w-12" />
                  <Skeleton className="h-5 w-12" />
                </div>
              </div>
              <div className="text-right">
                <Skeleton className="h-8 w-12" />
                <Skeleton className="h-3 w-16 mt-1" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3 mt-1" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Sparkles className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No Insights Found</CardTitle>
        <CardDescription className="max-w-sm">
          No AI insights match your current filters. Try adjusting your search criteria or run the analysis engine to generate new insights.
        </CardDescription>
      </CardContent>
    </Card>
  );
}

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

const SIGNALS_SIDEBAR_KEY = 'market-analyzer-signals-sidebar-visible';
const VIEW_MODE_KEY = 'market-analyzer-insights-view-mode';

type ViewMode = 'grid' | 'list';

/** Action badge config for compact list view */
const listActionConfig: Record<InsightAction, {
  color: string;
  icon: typeof TrendingUp;
  label: string;
}> = {
  STRONG_BUY: { color: 'bg-green-600 text-white', icon: TrendingUp, label: 'Strong Buy' },
  BUY: { color: 'bg-green-500 text-white', icon: TrendingUp, label: 'Buy' },
  HOLD: { color: 'bg-yellow-500 text-white', icon: Minus, label: 'Hold' },
  SELL: { color: 'bg-red-500 text-white', icon: TrendingDown, label: 'Sell' },
  STRONG_SELL: { color: 'bg-red-600 text-white', icon: TrendingDown, label: 'Strong Sell' },
  WATCH: { color: 'bg-blue-500 text-white', icon: Target, label: 'Watch' },
};

/** Compact list row for an insight */
function InsightListRow({
  insight,
  onClick,
  onSymbolClick,
}: {
  insight: DeepInsight;
  onClick: () => void;
  onSymbolClick: (symbol: string) => void;
}) {
  const action = listActionConfig[insight.action];
  const ActionIcon = action.icon;
  const confidencePct = Math.round(insight.confidence * 100);
  const confidenceColor =
    confidencePct >= 75 ? 'text-green-600 dark:text-green-400' :
    confidencePct >= 50 ? 'text-yellow-600 dark:text-yellow-400' :
    'text-red-600 dark:text-red-400';

  const dateStr = insight.created_at
    ? new Date(insight.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : '';

  return (
    <div
      className="flex items-center gap-3 px-4 py-3 border border-border/50 rounded-lg bg-card/80 backdrop-blur-sm hover:shadow-md hover:bg-accent/30 transition-all duration-150 cursor-pointer"
      onClick={onClick}
    >
      {/* Action badge */}
      <Badge className={cn(action.color, 'shadow-sm font-semibold px-2.5 py-0.5 text-xs shrink-0 gap-1')}>
        <ActionIcon className="w-3 h-3" />
        {action.label}
      </Badge>

      {/* Primary symbol */}
      {insight.primary_symbol ? (
        <Badge
          variant="outline"
          className="font-bold text-xs shrink-0 cursor-pointer hover:bg-primary/10 border-2 px-2 py-0.5"
          onClick={(e) => {
            e.stopPropagation();
            onSymbolClick(insight.primary_symbol!);
          }}
        >
          {insight.primary_symbol}
        </Badge>
      ) : (
        <span className="w-12 shrink-0" />
      )}

      {/* Title */}
      <span className="flex-1 min-w-0 text-sm font-medium truncate">
        {insight.title}
      </span>

      {/* Confidence */}
      <span className={cn('text-sm font-semibold tabular-nums shrink-0', confidenceColor)}>
        {confidencePct}%
      </span>

      {/* Date */}
      <span className="text-xs text-muted-foreground shrink-0 w-16 text-right">
        {dateStr}
      </span>
    </div>
  );
}

/**
 * Read the initial insight ID from the URL search params.
 * Must live inside a Suspense boundary because useSearchParams
 * requires it in Next.js static export.
 */
function InsightsPageInner() {
  const searchParams = useSearchParams();

  // Read ?id=<number> from the URL for deep-link / cross-page navigation support.
  const detailId = searchParams.get('id');
  const initialInsightId = detailId ? parseInt(detailId, 10) : null;
  const validInitialId =
    initialInsightId && !isNaN(initialInsightId) && initialInsightId > 0
      ? initialInsightId
      : null;

  // Manage the selected insight via React state rather than router.push().
  // This avoids Next.js App Router navigation issues in Tauri desktop builds
  // where router.push with query params can trigger a full-page navigation
  // instead of a client-side re-render, causing a redirect to the home page.
  const [selectedInsightId, setSelectedInsightId] = useState<number | null>(validInitialId);

  // Keep the URL in sync so that deep links and browser back/forward work.
  // pushState adds a history entry (enabling the browser back button to
  // return from detail to list), but does NOT trigger page navigation.
  const selectInsight = useCallback((id: number) => {
    setSelectedInsightId(id);
    if (typeof window !== 'undefined') {
      window.history.pushState(null, '', `/insights?id=${id}`);
    }
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedInsightId(null);
    if (typeof window !== 'undefined') {
      window.history.pushState(null, '', '/insights');
    }
  }, []);

  // Handle browser back/forward buttons (popstate).
  useEffect(() => {
    const handlePopState = () => {
      const params = new URLSearchParams(window.location.search);
      const id = params.get('id');
      const parsed = id ? parseInt(id, 10) : null;
      setSelectedInsightId(parsed && !isNaN(parsed) && parsed > 0 ? parsed : null);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  if (selectedInsightId) {
    return <InsightDetailView insightId={selectedInsightId} onBack={clearSelection} />;
  }

  return <InsightsListView onInsightClick={selectInsight} />;
}

// Wrap with Suspense because useSearchParams requires it in static export.
export default function InsightsPage() {
  return (
    <Suspense fallback={<InsightsListSkeleton />}>
      <InsightsPageInner />
    </Suspense>
  );
}

function InsightsListView({ onInsightClick }: { onInsightClick: (id: number) => void }) {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [actionFilter, setActionFilter] = useState<InsightAction | 'all'>('all');
  const [typeFilter, setTypeFilter] = useState<DeepInsightType | 'all'>('all');
  const [symbolFilter, setSymbolFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  // Default to false on server and initial client render to avoid hydration mismatch.
  // The stored preference is restored in useEffect after mount.
  const [showSignalsSidebar, setShowSignalsSidebar] = useState(false);
  const [sidebarHydrated, setSidebarHydrated] = useState(false);

  // View mode: default to 'grid' on server/initial render, restore from localStorage after mount.
  const [viewMode, setViewMode] = useState<ViewMode>('grid');

  useEffect(() => {
    const stored = localStorage.getItem(SIGNALS_SIDEBAR_KEY);
    // Default to true when no preference is stored
    setShowSignalsSidebar(stored !== null ? stored === 'true' : true);
    setSidebarHydrated(true);

    const storedView = localStorage.getItem(VIEW_MODE_KEY);
    if (storedView === 'grid' || storedView === 'list') {
      setViewMode(storedView);
    }
  }, []);

  // Save sidebar preference to localStorage
  const handleToggleSignalsSidebar = (visible: boolean) => {
    setShowSignalsSidebar(visible);
    localStorage.setItem(SIGNALS_SIDEBAR_KEY, String(visible));
  };

  // Save view mode preference to localStorage
  const handleSetViewMode = (mode: ViewMode) => {
    setViewMode(mode);
    localStorage.setItem(VIEW_MODE_KEY, mode);
  };

  const params: DeepInsightParams = {
    limit: ITEMS_PER_PAGE,
    offset: (page - 1) * ITEMS_PER_PAGE,
    ...(actionFilter !== 'all' && { action: actionFilter }),
    ...(typeFilter !== 'all' && { insight_type: typeFilter }),
    ...(symbolFilter && { symbol: symbolFilter.toUpperCase() }),
    ...(dateFrom && { start_date: dateFrom }),
    ...(dateTo && { end_date: dateTo }),
  };

  const { data, isLoading, error } = useDeepInsights(params);

  const totalPages = data ? Math.ceil(data.total / ITEMS_PER_PAGE) : 1;

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSymbolClick = (symbol: string) => {
    router.push(`/stocks/${symbol}`);
  };

  const handleInsightClick = (insightId: number) => {
    onInsightClick(insightId);
  };

  const handleClearFilters = () => {
    setActionFilter('all');
    setTypeFilter('all');
    setSymbolFilter('');
    setDateFrom('');
    setDateTo('');
    setPage(1);
  };

  const hasFilters = actionFilter !== 'all' || typeFilter !== 'all' || symbolFilter !== '' || dateFrom !== '' || dateTo !== '';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight">AI Insights</h1>
          </div>
          <p className="text-muted-foreground mt-1">
            Deep analysis synthesized from multiple AI analysts
          </p>
        </div>
      </div>

      {/* Main Layout: Insights + Signals Sidebar */}
      <div className={`grid grid-cols-1 ${showSignalsSidebar ? 'lg:grid-cols-4' : 'lg:grid-cols-1'} gap-6`}>
        {/* Main Content Column */}
        <div className={`${showSignalsSidebar ? 'lg:col-span-3' : 'lg:col-span-1'} space-y-6`}>
          {/* Filters */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex flex-wrap gap-4 items-end">
                <div className="flex-1 min-w-[200px]">
                  <label className="text-sm font-medium mb-2 block">Symbol</label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search by symbol..."
                      value={symbolFilter}
                      onChange={(e) => {
                        setSymbolFilter(e.target.value);
                        setPage(1);
                      }}
                      className="pl-9"
                    />
                  </div>
                </div>
                <div className="w-[180px]">
                  <label className="text-sm font-medium mb-2 block">Action</label>
                  <Select
                    value={actionFilter}
                    onValueChange={(value) => {
                      setActionFilter(value as InsightAction | 'all');
                      setPage(1);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {actionOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="w-[180px]">
                  <label className="text-sm font-medium mb-2 block">Type</label>
                  <Select
                    value={typeFilter}
                    onValueChange={(value) => {
                      setTypeFilter(value as DeepInsightType | 'all');
                      setPage(1);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {typeOptions.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex gap-2 items-end">
                  <div className="w-[150px]">
                    <label className="text-sm font-medium mb-2 block">From</label>
                    <div className="relative">
                      <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                      <Input
                        type="date"
                        value={dateFrom}
                        onChange={(e) => {
                          setDateFrom(e.target.value);
                          setPage(1);
                        }}
                        max={dateTo || undefined}
                        className="pl-9"
                      />
                    </div>
                  </div>
                  <div className="w-[150px]">
                    <label className="text-sm font-medium mb-2 block">To</label>
                    <Input
                      type="date"
                      value={dateTo}
                      onChange={(e) => {
                        setDateTo(e.target.value);
                        setPage(1);
                      }}
                      min={dateFrom || undefined}
                    />
                  </div>
                </div>
                {hasFilters && (
                  <Button variant="ghost" size="sm" onClick={handleClearFilters}>
                    Clear Filters
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Results Count + View Toggle */}
          {data && !isLoading && (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <p className="text-sm text-muted-foreground">
                  Showing {data.items.length} of {data.total} insights
                </p>
                {hasFilters && (
                  <Badge variant="secondary" className="gap-1">
                    <Filter className="h-3 w-3" />
                    Filtered
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-1 border rounded-md p-0.5">
                <Button
                  variant={viewMode === 'grid' ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 w-7 p-0"
                  onClick={() => handleSetViewMode('grid')}
                  aria-label="Grid view"
                >
                  <LayoutGrid className="h-4 w-4" />
                </Button>
                <Button
                  variant={viewMode === 'list' ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 w-7 p-0"
                  onClick={() => handleSetViewMode('list')}
                  aria-label="List view"
                >
                  <List className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}

          {/* Insights List */}
          {isLoading ? (
            <InsightsListSkeleton />
          ) : error ? (
            <ConnectionError error={error} />
          ) : !data || data.items.length === 0 ? (
            <EmptyState />
          ) : (
            <>
              {viewMode === 'grid' ? (
                <div className="grid gap-4 md:grid-cols-2">
                  {data.items.map((insight) => (
                    <DeepInsightCard
                      key={insight.id}
                      insight={insight}
                      onSymbolClick={handleSymbolClick}
                      onClick={() => handleInsightClick(insight.id)}
                    />
                  ))}
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {data.items.map((insight) => (
                    <InsightListRow
                      key={insight.id}
                      insight={insight}
                      onClick={() => handleInsightClick(insight.id)}
                      onSymbolClick={handleSymbolClick}
                    />
                  ))}
                </div>
              )}

              {/* Pagination */}
              <Pagination
                currentPage={page}
                totalPages={totalPages}
                onPageChange={handlePageChange}
              />
            </>
          )}
        </div>

        {/* Sidebar: Statistical Signals */}
        {showSignalsSidebar && (
          <div className="lg:col-span-1">
            <div className="lg:sticky lg:top-6">
              <StatisticalSignalsCard
                showAll
                maxSignals={8}
                onClose={() => handleToggleSignalsSidebar(false)}
              />
            </div>
          </div>
        )}
      </div>

      {/* Floating button to show signals sidebar when hidden */}
      {sidebarHydrated && !showSignalsSidebar && (
        <Button
          variant="outline"
          size="sm"
          className="fixed bottom-6 right-6 shadow-lg gap-2 z-50"
          onClick={() => handleToggleSignalsSidebar(true)}
        >
          <Activity className="h-4 w-4" />
          Show Signals
          <PanelRightOpen className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
