'use client';

import { useRouter } from 'next/navigation';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { useReportList } from '@/lib/hooks/use-reports';
import type { ReportSummary } from '@/lib/types/report';
import { FileText, Clock, Sparkles, ExternalLink } from 'lucide-react';

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

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return '--';
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs}s`;
}

const regimeColors: Record<string, string> = {
  bullish: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  bearish: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  neutral: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  volatile: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  'risk-off': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  'risk-on': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
};

function getRegimeColor(regime: string | null): string {
  if (!regime) return 'bg-muted text-muted-foreground';
  const lower = regime.toLowerCase();
  for (const [key, cls] of Object.entries(regimeColors)) {
    if (lower.includes(key)) return cls;
  }
  return 'bg-muted text-muted-foreground';
}

function ReportCard({ report, onClick }: { report: ReportSummary; onClick: () => void }) {
  return (
    <Card
      className="cursor-pointer hover:shadow-md transition-shadow"
      onClick={onClick}
    >
      <CardContent className="p-5 space-y-3">
        {/* Top: date and duration */}
        <div className="flex items-start justify-between gap-2">
          <div className="text-sm font-medium">
            {formatDate(report.completed_at || report.started_at)}
          </div>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            {formatDuration(report.elapsed_seconds)}
          </div>
        </div>

        {/* Market regime */}
        {report.market_regime && (
          <Badge
            variant="secondary"
            className={getRegimeColor(report.market_regime)}
          >
            {report.market_regime}
          </Badge>
        )}

        {/* Top sectors */}
        {report.top_sectors.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {report.top_sectors.map((sector) => (
              <Badge key={sector} variant="outline" className="text-xs">
                {sector}
              </Badge>
            ))}
          </div>
        )}

        {/* Discovery summary (truncated) */}
        {report.discovery_summary && (
          <p className="text-sm text-muted-foreground line-clamp-2">
            {report.discovery_summary}
          </p>
        )}

        {/* Bottom: insights count and published status */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Sparkles className="h-3 w-3" />
            {report.insights_count} insight{report.insights_count !== 1 ? 's' : ''}
          </div>
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

function ReportsListSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="p-5 space-y-3">
            <div className="flex items-start justify-between">
              <Skeleton className="h-4 w-36" />
              <Skeleton className="h-4 w-14" />
            </div>
            <Skeleton className="h-5 w-20" />
            <div className="flex gap-1">
              <Skeleton className="h-5 w-16" />
              <Skeleton className="h-5 w-16" />
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
          Analysis reports will appear here after running autonomous deep analysis.
          Reports contain market regime assessment, sector rotation signals, and
          actionable investment insights.
        </CardDescription>
      </CardContent>
    </Card>
  );
}

export default function ReportsPage() {
  const router = useRouter();
  const { data, isLoading, error } = useReportList({ limit: 50 });

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2">
          <FileText className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Analysis Reports</h1>
        </div>
        <p className="text-muted-foreground mt-1">
          Full analysis reports from autonomous deep analysis runs
        </p>
      </div>

      {/* Results Count */}
      {data && !isLoading && data.items.length > 0 && (
        <p className="text-sm text-muted-foreground">
          {data.total} report{data.total !== 1 ? 's' : ''}
        </p>
      )}

      {/* Reports Grid */}
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
      ) : !data || data.items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.items.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              onClick={() => router.push(`/reports/${report.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
