'use client';

import Link from 'next/link';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { UntrackedNotice } from './track-record-badge';
import { formatRelativeTime, getInsightTypeLabel } from '@/lib/hooks/use-insights';
import type { Insight } from '@/types';
import {
  TrendingUp,
  AlertTriangle,
  BarChart3,
  Activity,
  Building2,
  DollarSign,
  Info,
  Eye,
  ShieldAlert,
} from 'lucide-react';

interface InsightCardProps {
  insight: Insight;
  onClick?: () => void;
}

// --- Severity-to-action mapping for layman language ---

interface SeverityActionInfo {
  label: string;
  explanation: string;
  borderColor: string;
  badgeBg: string;
  badgeText: string;
}

function getSeverityAction(severity: Insight['severity']): SeverityActionInfo {
  switch (severity) {
    case 'alert':
      return {
        label: 'Sell',
        explanation: 'Consider selling -- warning signs detected',
        borderColor: 'border-l-red-500',
        badgeBg: 'bg-red-500',
        badgeText: 'text-white',
      };
    case 'warning':
      return {
        label: 'Watch',
        explanation: 'Keep an eye on this -- conditions are shifting',
        borderColor: 'border-l-blue-500',
        badgeBg: 'bg-blue-500',
        badgeText: 'text-white',
      };
    case 'info':
    default:
      return {
        label: 'Hold',
        explanation: 'Conditions look stable -- no immediate action needed',
        borderColor: 'border-l-yellow-500',
        badgeBg: 'bg-yellow-500',
        badgeText: 'text-white',
      };
  }
}

function getTypeIcon(type: Insight['type']) {
  const iconClass = 'h-3.5 w-3.5';
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
      return <ShieldAlert className={iconClass} />;
    case 'warning':
      return <Eye className={iconClass} />;
    case 'info':
    default:
      return <Info className={iconClass} />;
  }
}

/** Generate a simple plain-English summary from insight type */
function getLaymanSummary(type: Insight['type'], severity: Insight['severity']): string {
  const urgency = severity === 'alert' ? 'Urgent' : severity === 'warning' ? 'Notable' : 'Informational';
  switch (type) {
    case 'pattern':
      return `${urgency} price pattern detected that may signal a trend change`;
    case 'anomaly':
      return `${urgency} unusual market behavior that deviates from normal patterns`;
    case 'sector':
      return `${urgency} shift in sector performance worth monitoring`;
    case 'technical':
      return `${urgency} technical indicator signal based on price and volume data`;
    case 'economic':
      return `${urgency} economic data point that may affect market direction`;
    default:
      return `${urgency} market signal detected`;
  }
}

export function InsightCard({ insight, onClick }: InsightCardProps) {
  const severityAction = getSeverityAction(insight.severity);

  return (
    <Card
      className={cn(
        'cursor-pointer',
        'bg-card/80 backdrop-blur-sm border border-border/50',
        'border-l-4',
        severityAction.borderColor,
        'hover:scale-[1.02] hover:shadow-lg transition-all duration-200'
      )}
      onClick={onClick}
    >
      {/* Header: Action badge left, track-record notice right */}
      <div className="px-5 pt-4 pb-2">
        <div className="flex items-start justify-between gap-3">
          {/* Left: Action + Type badges */}
          <div className="flex items-center gap-2 flex-wrap">
            <Badge className={cn('gap-1 font-semibold', severityAction.badgeBg, severityAction.badgeText)}>
              {getSeverityIcon(insight.severity)}
              {severityAction.label}
            </Badge>
            <Badge variant="outline" className="gap-1 text-xs">
              {getTypeIcon(insight.type)}
              {getInsightTypeLabel(insight.type)}
            </Badge>
          </div>

          {/* Right: these signals carry a stated confidence but nothing grades
              their outcomes, so there is no hit rate to show and the number is
              not printed. */}
          <UntrackedNotice className="shrink-0" />
        </div>
      </div>

      <CardContent className="px-5 pb-4 pt-0 space-y-2.5">
        {/* Symbol + Timestamp row */}
        <div className="flex items-center gap-2">
          {insight.symbol && (
            <Link
              href={`/stocks/${insight.symbol}`}
              onClick={(e) => e.stopPropagation()}
              className="hover:underline"
            >
              <Badge variant="secondary" className="font-mono font-bold text-sm px-2.5 py-0.5">
                {insight.symbol}
              </Badge>
            </Link>
          )}
          <span className="text-xs text-muted-foreground ml-auto whitespace-nowrap">
            {formatRelativeTime(insight.created_at)}
          </span>
        </div>

        {/* Title */}
        <h3 className="text-sm font-semibold leading-snug line-clamp-2">
          {insight.title}
        </h3>

        {/* Layman summary */}
        <p className="text-xs text-muted-foreground italic leading-relaxed">
          {getLaymanSummary(insight.type, insight.severity)}
        </p>

        {/* Description */}
        <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
          {insight.description || insight.content}
        </p>

        {/* Action explanation */}
        <div className={cn(
          'flex items-start gap-2 rounded-md px-3 py-2 text-xs',
          'bg-muted/60'
        )}>
          {getSeverityIcon(insight.severity)}
          <span className="text-muted-foreground">{severityAction.explanation}</span>
        </div>
      </CardContent>
    </Card>
  );
}
