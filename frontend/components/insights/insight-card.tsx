'use client';

import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { formatRelativeTime, getSeverityClasses, getInsightTypeLabel } from '@/lib/hooks/use-insights';
import type { Insight } from '@/types';
import {
  TrendingUp,
  AlertTriangle,
  BarChart3,
  Activity,
  Building2,
  DollarSign,
  Info,
  AlertCircle,
} from 'lucide-react';

interface InsightCardProps {
  insight: Insight;
  onClick?: () => void;
}

function getTypeIcon(type: Insight['type']) {
  const iconClass = 'h-4 w-4';
  switch (type) {
    case 'pattern':
      return <TrendingUp className={iconClass} />;
    case 'anomaly':
      return <AlertTriangle className={iconClass} />;
    case 'sector':
      return <Building2 className={iconClass} />;
    case 'technical':
      return <BarChart3 className={iconClass} />;
    case 'economic':
      return <DollarSign className={iconClass} />;
    default:
      return <Activity className={iconClass} />;
  }
}

function getSeverityIcon(severity: Insight['severity']) {
  const iconClass = 'h-3 w-3';
  switch (severity) {
    case 'alert':
      return <AlertCircle className={iconClass} />;
    case 'warning':
      return <AlertTriangle className={iconClass} />;
    case 'info':
    default:
      return <Info className={iconClass} />;
  }
}

function getSeverityBadgeVariant(severity: Insight['severity']): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (severity) {
    case 'alert':
      return 'destructive';
    case 'warning':
      return 'secondary';
    case 'info':
    default:
      return 'outline';
  }
}

export function InsightCard({ insight, onClick }: InsightCardProps) {
  const severityClasses = getSeverityClasses(insight.severity);
  const confidencePercent = insight.confidence ? Math.round(insight.confidence * 100) : null;

  return (
    <Card
      className={cn(
        'cursor-pointer transition-all hover:shadow-md',
        'border-l-4',
        insight.severity === 'alert' && 'border-l-red-500',
        insight.severity === 'warning' && 'border-l-yellow-500',
        insight.severity === 'info' && 'border-l-blue-500'
      )}
      onClick={onClick}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="outline" className="gap-1">
              {getTypeIcon(insight.type)}
              {getInsightTypeLabel(insight.type)}
            </Badge>
            <Badge variant={getSeverityBadgeVariant(insight.severity)} className="gap-1">
              {getSeverityIcon(insight.severity)}
              {insight.severity}
            </Badge>
            {insight.symbol && (
              <Link
                href={`/stocks/${insight.symbol}`}
                onClick={(e) => e.stopPropagation()}
                className="hover:underline"
              >
                <Badge variant="secondary">{insight.symbol}</Badge>
              </Link>
            )}
          </div>
          <span className="text-xs text-muted-foreground whitespace-nowrap">
            {formatRelativeTime(insight.created_at)}
          </span>
        </div>
        <CardTitle className="text-base mt-2">{insight.title}</CardTitle>
      </CardHeader>
      <CardContent>
        <CardDescription className="line-clamp-2">
          {insight.description || insight.content}
        </CardDescription>
        {confidencePercent !== null && (
          <div className="mt-3">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="text-muted-foreground">Confidence</span>
              <span className="font-medium">{confidencePercent}%</span>
            </div>
            <div className="h-1.5 w-full bg-secondary rounded-full overflow-hidden">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  confidencePercent >= 80 && 'bg-green-500',
                  confidencePercent >= 60 && confidencePercent < 80 && 'bg-yellow-500',
                  confidencePercent < 60 && 'bg-red-500'
                )}
                style={{ width: `${confidencePercent}%` }}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
