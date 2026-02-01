'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { DeepInsightCard } from '@/components/insights/deep-insight-card';
import { StatisticalSignalsCard } from '@/components/insights/statistical-signals-card';
import { useDeepInsights, DeepInsightParams } from '@/lib/hooks/use-deep-insights';
import type { DeepInsightType, InsightAction } from '@/types';
import { Sparkles, ChevronLeft, ChevronRight, Search, Filter, Activity, PanelRightOpen } from 'lucide-react';

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

export default function InsightsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [actionFilter, setActionFilter] = useState<InsightAction | 'all'>('all');
  const [typeFilter, setTypeFilter] = useState<DeepInsightType | 'all'>('all');
  const [symbolFilter, setSymbolFilter] = useState('');
  const [showSignalsSidebar, setShowSignalsSidebar] = useState(true);

  // Load sidebar preference from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(SIGNALS_SIDEBAR_KEY);
    if (stored !== null) {
      setShowSignalsSidebar(stored === 'true');
    }
  }, []);

  // Save sidebar preference to localStorage
  const handleToggleSignalsSidebar = (visible: boolean) => {
    setShowSignalsSidebar(visible);
    localStorage.setItem(SIGNALS_SIDEBAR_KEY, String(visible));
  };

  const params: DeepInsightParams = {
    limit: ITEMS_PER_PAGE,
    offset: (page - 1) * ITEMS_PER_PAGE,
    ...(actionFilter !== 'all' && { action: actionFilter }),
    ...(typeFilter !== 'all' && { insight_type: typeFilter }),
    ...(symbolFilter && { symbol: symbolFilter.toUpperCase() }),
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
    router.push(`/insights/${insightId}`);
  };

  const handleClearFilters = () => {
    setActionFilter('all');
    setTypeFilter('all');
    setSymbolFilter('');
    setPage(1);
  };

  const hasFilters = actionFilter !== 'all' || typeFilter !== 'all' || symbolFilter !== '';

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
                {hasFilters && (
                  <Button variant="ghost" size="sm" onClick={handleClearFilters}>
                    Clear Filters
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Results Count */}
          {data && !isLoading && (
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
          )}

          {/* Insights List */}
          {isLoading ? (
            <InsightsListSkeleton />
          ) : error ? (
            <Card className="py-12">
              <CardContent className="flex flex-col items-center justify-center text-center">
                <CardTitle className="text-lg mb-2 text-destructive">
                  Error Loading Insights
                </CardTitle>
                <CardDescription>
                  {error instanceof Error ? error.message : 'An unexpected error occurred'}
                </CardDescription>
              </CardContent>
            </Card>
          ) : !data || data.items.length === 0 ? (
            <EmptyState />
          ) : (
            <>
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
      {!showSignalsSidebar && (
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
