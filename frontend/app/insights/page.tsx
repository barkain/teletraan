'use client';

import { useState, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { InsightCard } from '@/components/insights/insight-card';
import { InsightFilters } from '@/components/insights/insight-filters';
import { InsightDetail } from '@/components/insights/insight-detail';
import { useInsights } from '@/lib/hooks/use-insights';
import type { Insight, InsightFilters as InsightFiltersType } from '@/types';
import { Lightbulb, ChevronLeft, ChevronRight } from 'lucide-react';
import { ExportDialog } from '@/components/export';

// Helper to format date as YYYY-MM-DD for input[type="date"]
function formatDateForInput(date: Date): string {
  return date.toISOString().split('T')[0];
}

// Get default date range (30 days ago to today)
function getDefaultDateRange() {
  const endDate = new Date();
  const startDate = new Date();
  startDate.setDate(startDate.getDate() - 30);
  return {
    startDate: formatDateForInput(startDate),
    endDate: formatDateForInput(endDate),
  };
}

function InsightsListSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Skeleton className="h-5 w-20" />
              <Skeleton className="h-5 w-16" />
            </div>
            <Skeleton className="h-5 w-3/4 mt-2" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3 mt-1" />
            <Skeleton className="h-2 w-full mt-4" />
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
          <Lightbulb className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No Insights Found</CardTitle>
        <CardDescription className="max-w-sm">
          No insights match your current filters. Try adjusting your search criteria or clear the filters to see all insights.
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

export default function InsightsPage() {
  // Compute default dates once using useMemo to avoid hydration mismatch
  const defaultDates = useMemo(() => getDefaultDateRange(), []);

  const [filters, setFilters] = useState<InsightFiltersType>(() => ({
    type: 'all',
    severity: 'all',
    search: '',
    page: 1,
    perPage: 12,
    startDate: defaultDates.startDate,
    endDate: defaultDates.endDate,
  }));

  const [selectedInsight, setSelectedInsight] = useState<Insight | null>(null);

  const { data, isLoading, error } = useInsights(filters);

  const handleFiltersChange = (newFilters: InsightFiltersType) => {
    setFilters({ ...newFilters, perPage: filters.perPage });
  };

  const handlePageChange = (page: number) => {
    setFilters({ ...filters, page });
    // Scroll to top of list
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Insights</h1>
          <p className="text-muted-foreground">
            AI-generated market analysis and insights
          </p>
        </div>
        <ExportDialog
          type="insights"
          insightFilters={{
            type: filters.type === 'all' ? undefined : filters.type,
            severity: filters.severity === 'all' ? undefined : filters.severity,
          }}
        />
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <InsightFilters filters={filters} onFiltersChange={handleFiltersChange} />
        </CardContent>
      </Card>

      {/* Results Count */}
      {data && !isLoading && (
        <p className="text-sm text-muted-foreground">
          Showing {data.items.length} of {data.total} insights
        </p>
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
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {data.items.map((insight) => (
              <InsightCard
                key={insight.id}
                insight={insight}
                onClick={() => setSelectedInsight(insight)}
              />
            ))}
          </div>

          {/* Pagination */}
          <Pagination
            currentPage={data.page}
            totalPages={data.total_pages}
            onPageChange={handlePageChange}
          />
        </>
      )}

      {/* Detail Dialog */}
      {selectedInsight && (
        <InsightDetail
          insight={selectedInsight}
          open={!!selectedInsight}
          onOpenChange={(open) => !open && setSelectedInsight(null)}
        />
      )}
    </div>
  );
}
