'use client';

import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import type { Insight } from '@/types';
import { ArrowRight, TrendingUp, TrendingDown, BarChart3, Newspaper } from 'lucide-react';

interface InsightsSummaryProps {
  insights: Insight[] | undefined;
  isLoading: boolean;
}

function getTypeIcon(type: Insight['type']) {
  switch (type) {
    case 'technical':
      return <BarChart3 className="h-4 w-4" />;
    case 'pattern':
      return <TrendingUp className="h-4 w-4" />;
    case 'anomaly':
      return <TrendingDown className="h-4 w-4" />;
    case 'sector':
      return <Newspaper className="h-4 w-4" />;
    case 'economic':
      return <BarChart3 className="h-4 w-4" />;
    default:
      return null;
  }
}

function getTypeVariant(type: Insight['type']): 'default' | 'secondary' | 'outline' | 'destructive' {
  switch (type) {
    case 'technical':
      return 'default';
    case 'pattern':
      return 'secondary';
    case 'anomaly':
      return 'outline';
    case 'sector':
      return 'outline';
    case 'economic':
      return 'secondary';
    default:
      return 'default';
  }
}

function getSeverityVariant(confidence: number | undefined): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (!confidence) return 'outline';
  if (confidence >= 0.85) return 'default';
  if (confidence >= 0.7) return 'secondary';
  return 'outline';
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 60) {
    return `${diffMins}m ago`;
  } else if (diffHours < 24) {
    return `${diffHours}h ago`;
  } else {
    return `${diffDays}d ago`;
  }
}

function InsightsSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center justify-between border-b pb-4 last:border-b-0 last:pb-0">
          <div className="flex-1 space-y-2">
            <div className="flex items-center gap-2">
              <Skeleton className="h-5 w-16" />
              <Skeleton className="h-5 w-20" />
            </div>
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-16" />
          </div>
        </div>
      ))}
    </div>
  );
}

function InsightItem({ insight }: { insight: Insight }) {
  return (
    <div className="flex items-start justify-between border-b pb-4 last:border-b-0 last:pb-0 gap-4">
      <div className="flex-1 space-y-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant={getTypeVariant(insight.type)} className="gap-1">
            {getTypeIcon(insight.type)}
            {insight.type}
          </Badge>
          <Badge variant={getSeverityVariant(insight.confidence)}>
            {insight.symbol}
          </Badge>
        </div>
        <p className="font-medium text-sm truncate">{insight.title}</p>
        <p className="text-xs text-muted-foreground">
          {formatTimestamp(insight.created_at)}
        </p>
      </div>
    </div>
  );
}

export function InsightsSummary({ insights, isLoading }: InsightsSummaryProps) {
  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Recent Signals</CardTitle>
            <CardDescription>
              Technical signals from your watchlist
            </CardDescription>
          </div>
          <Link
            href="/signals"
            className={cn(
              'flex items-center gap-1 text-sm text-muted-foreground',
              'hover:text-foreground transition-colors'
            )}
          >
            View all
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <InsightsSkeleton />
        ) : !insights || insights.length === 0 ? (
          <div className="py-8 text-center text-muted-foreground">
            No signals available
          </div>
        ) : (
          <div className="space-y-4">
            {insights.slice(0, 5).map((insight) => (
              <InsightItem key={insight.id} insight={insight} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
