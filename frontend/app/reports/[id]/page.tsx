'use client';

import { use, useState } from 'react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { useReportDetail, usePublishReport } from '@/lib/hooks/use-reports';
import { api } from '@/lib/api';
import type { ReportInsight } from '@/lib/types/report';
import {
  ArrowLeft,
  Clock,
  ExternalLink,
  FileText,
  Globe,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Target,
  AlertTriangle,
  TrendingUp,
  Eye,
} from 'lucide-react';

// ---- Helpers ----

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'Unknown date';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
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

const actionColors: Record<string, string> = {
  STRONG_BUY: 'bg-green-600 text-white',
  BUY: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  HOLD: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  SELL: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  STRONG_SELL: 'bg-red-600 text-white',
  WATCH: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
};

function getActionColor(action: string | null): string {
  if (!action) return 'bg-muted text-muted-foreground';
  return actionColors[action] || 'bg-muted text-muted-foreground';
}

function formatAction(action: string | null): string {
  if (!action) return 'N/A';
  return action.replace(/_/g, ' ');
}

// ---- Components ----

function InsightCard({ insight }: { insight: ReportInsight }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        {/* Top row: action badge + symbol + title */}
        <div className="flex items-start gap-3">
          <Badge className={`shrink-0 ${getActionColor(insight.action)}`}>
            {formatAction(insight.action)}
          </Badge>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              {insight.primary_symbol && (
                <Link
                  href={`/stocks/${insight.primary_symbol}`}
                  className="font-mono font-semibold text-primary hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  {insight.primary_symbol}
                </Link>
              )}
              {insight.insight_type && (
                <Badge variant="outline" className="text-xs">
                  {insight.insight_type}
                </Badge>
              )}
            </div>
            <p className="text-sm font-medium mt-1">{insight.title}</p>
          </div>
          {/* Confidence */}
          {insight.confidence !== null && (
            <div className="text-right shrink-0">
              <div className="text-lg font-bold">
                {Math.round(insight.confidence * 100)}%
              </div>
              <div className="text-xs text-muted-foreground">confidence</div>
            </div>
          )}
        </div>

        {/* Expand/collapse toggle */}
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-center gap-1 text-xs text-muted-foreground"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <>
              <ChevronUp className="h-3 w-3" /> Less
            </>
          ) : (
            <>
              <ChevronDown className="h-3 w-3" /> More
            </>
          )}
        </Button>

        {/* Expanded details */}
        {expanded && (
          <div className="space-y-3 pt-1 border-t">
            {/* Thesis */}
            {insight.thesis && (
              <div>
                <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1">
                  Thesis
                </h4>
                <p className="text-sm">{insight.thesis}</p>
              </div>
            )}

            {/* Targets */}
            {(insight.entry_zone || insight.target_price || insight.stop_loss) && (
              <div className="grid grid-cols-3 gap-2">
                {insight.entry_zone && (
                  <div className="text-center p-2 rounded bg-muted/50">
                    <div className="text-xs text-muted-foreground">Entry</div>
                    <div className="text-sm font-medium">{insight.entry_zone}</div>
                  </div>
                )}
                {insight.target_price && (
                  <div className="text-center p-2 rounded bg-green-50 dark:bg-green-950/30">
                    <div className="text-xs text-muted-foreground flex items-center justify-center gap-1">
                      <TrendingUp className="h-3 w-3" /> Target
                    </div>
                    <div className="text-sm font-medium text-green-700 dark:text-green-400">
                      {insight.target_price}
                    </div>
                  </div>
                )}
                {insight.stop_loss && (
                  <div className="text-center p-2 rounded bg-red-50 dark:bg-red-950/30">
                    <div className="text-xs text-muted-foreground flex items-center justify-center gap-1">
                      <AlertTriangle className="h-3 w-3" /> Stop
                    </div>
                    <div className="text-sm font-medium text-red-700 dark:text-red-400">
                      {insight.stop_loss}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Time horizon */}
            {insight.time_horizon && (
              <div className="flex items-center gap-2 text-sm">
                <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">Horizon:</span>
                <span>{insight.time_horizon}</span>
              </div>
            )}

            {/* Risk factors */}
            {insight.risk_factors.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-1 flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3" /> Risk Factors
                </h4>
                <ul className="list-disc list-inside text-sm space-y-0.5 text-muted-foreground">
                  {insight.risk_factors.map((risk, i) => (
                    <li key={i}>{risk}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Invalidation trigger */}
            {insight.invalidation_trigger && (
              <div className="text-sm">
                <span className="text-muted-foreground">Invalidation: </span>
                {insight.invalidation_trigger}
              </div>
            )}

            {/* Related symbols */}
            {insight.related_symbols.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-muted-foreground">Related:</span>
                {insight.related_symbols.map((sym) => (
                  <Link
                    key={sym}
                    href={`/stocks/${sym}`}
                    className="text-xs font-mono text-primary hover:underline"
                  >
                    {sym}
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-64" />
      <div className="flex gap-2">
        <Skeleton className="h-6 w-20" />
        <Skeleton className="h-6 w-20" />
        <Skeleton className="h-6 w-16" />
      </div>
      <Card>
        <CardContent className="p-6 space-y-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </CardContent>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardContent className="p-4 space-y-3">
              <div className="flex items-start gap-3">
                <Skeleton className="h-6 w-20" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-4 w-full" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ---- Page ----

interface ReportDetailPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default function ReportDetailPage({ params }: ReportDetailPageProps) {
  const resolvedParams = use(params);
  const reportId = resolvedParams.id;
  const { data: report, isLoading, error } = useReportDetail(reportId);
  const publishMutation = usePublishReport();

  const handlePublish = () => {
    publishMutation.mutate(reportId);
  };

  const handleViewHtml = () => {
    window.open(api.reports.htmlUrl(reportId), '_blank');
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" className="gap-1" asChild>
          <Link href="/reports">
            <ArrowLeft className="h-4 w-4" /> Back to Reports
          </Link>
        </Button>
        <DetailSkeleton />
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" size="sm" className="gap-1" asChild>
          <Link href="/reports">
            <ArrowLeft className="h-4 w-4" /> Back to Reports
          </Link>
        </Button>
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <CardTitle className="text-lg mb-2 text-destructive">
              {error ? 'Error Loading Report' : 'Report Not Found'}
            </CardTitle>
            <CardDescription>
              {error instanceof Error
                ? error.message
                : `Report "${reportId}" could not be found.`}
            </CardDescription>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <Button variant="ghost" size="sm" className="gap-1" asChild>
        <Link href="/reports">
          <ArrowLeft className="h-4 w-4" /> Back to Reports
        </Link>
      </Button>

      {/* Header */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <FileText className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">
            {formatDate(report.completed_at || report.started_at)}
          </h1>
        </div>

        {/* Badges row */}
        <div className="flex flex-wrap items-center gap-2">
          {report.market_regime && (
            <Badge className={getRegimeColor(report.market_regime)}>
              {report.market_regime}
            </Badge>
          )}
          <Badge variant="outline" className="gap-1">
            <Clock className="h-3 w-3" />
            {formatDuration(report.elapsed_seconds)}
          </Badge>
          <Badge variant="outline" className="gap-1">
            <Sparkles className="h-3 w-3" />
            {report.insights_count} insight{report.insights_count !== 1 ? 's' : ''}
          </Badge>
          {report.top_sectors.map((sector) => (
            <Badge key={sector} variant="secondary">
              {sector}
            </Badge>
          ))}
        </div>

        {/* Phases completed */}
        {report.phases_completed.length > 0 && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Target className="h-4 w-4" />
            Phases: {report.phases_completed.join(' > ')}
          </div>
        )}
      </div>

      {/* Discovery summary */}
      {report.discovery_summary && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Eye className="h-4 w-4" />
              Discovery Summary
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm leading-relaxed whitespace-pre-wrap">
              {report.discovery_summary}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Action buttons */}
      <div className="flex flex-wrap gap-3">
        <Button variant="outline" className="gap-2" onClick={handleViewHtml}>
          <FileText className="h-4 w-4" />
          View HTML Report
          <ExternalLink className="h-3 w-3" />
        </Button>

        {report.published_url ? (
          <Button variant="outline" className="gap-2" asChild>
            <a href={report.published_url} target="_blank" rel="noopener noreferrer">
              <Globe className="h-4 w-4" />
              View Published Report
              <ExternalLink className="h-3 w-3" />
            </a>
          </Button>
        ) : (
          <Button
            variant="default"
            className="gap-2"
            onClick={handlePublish}
            disabled={publishMutation.isPending}
          >
            <Globe className="h-4 w-4" />
            {publishMutation.isPending ? 'Publishing...' : 'Publish to GitHub'}
          </Button>
        )}

        {/* Show published URL after successful publish */}
        {publishMutation.isSuccess && publishMutation.data && (
          <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
            Published:
            <a
              href={publishMutation.data.published_url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:no-underline"
            >
              {publishMutation.data.published_url}
            </a>
          </div>
        )}

        {publishMutation.isError && (
          <div className="text-sm text-destructive">
            {publishMutation.error instanceof Error
              ? publishMutation.error.message
              : 'Failed to publish report'}
          </div>
        )}
      </div>

      {/* Insights section */}
      {report.insights.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            Insights ({report.insights.length})
          </h2>
          <div className="grid gap-4 md:grid-cols-2">
            {report.insights.map((insight) => (
              <InsightCard key={insight.id} insight={insight} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
