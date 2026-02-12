'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import {
  formatRelativeTime,
  getInsightTypeLabel,
} from '@/lib/hooks/use-insights';
import { AnnotationForm } from './annotation-form';
import type { Insight } from '@/types';
import {
  TrendingUp,
  AlertTriangle,
  BarChart3,
  Building2,
  DollarSign,
  Activity,
  Info,
  ExternalLink,
  MessageSquare,
  Clock,
  ChevronDown,
  ChevronRight,
  Eye,
  ShieldAlert,
  Gauge,
  Calendar,
  Tag,
  Database,
} from 'lucide-react';

interface InsightDetailProps {
  insight: Insight;
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
        explanation: 'Consider selling -- warning signs detected. This signal suggests unfavorable conditions that could lead to losses if no action is taken.',
        borderColor: 'border-l-red-500',
        badgeBg: 'bg-red-500',
        badgeText: 'text-white',
      };
    case 'warning':
      return {
        label: 'Watch',
        explanation: 'Keep an eye on this -- conditions are shifting. This signal is not urgent, but the situation is developing and may require action soon.',
        borderColor: 'border-l-blue-500',
        badgeBg: 'bg-blue-500',
        badgeText: 'text-white',
      };
    case 'info':
    default:
      return {
        label: 'Hold',
        explanation: 'Conditions look stable -- no immediate action needed. This is an informational signal that may be useful for long-term planning.',
        borderColor: 'border-l-yellow-500',
        badgeBg: 'bg-yellow-500',
        badgeText: 'text-white',
      };
  }
}

function getTypeIcon(type: Insight['type'], className: string = 'h-5 w-5') {
  switch (type) {
    case 'pattern':
      return <TrendingUp className={className} />;
    case 'anomaly':
      return <AlertTriangle className={className} />;
    case 'sector':
      return <Building2 className={className} />;
    case 'technical':
      return <BarChart3 className={className} />;
    case 'economic':
      return <DollarSign className={className} />;
    default:
      return <Activity className={className} />;
  }
}

function getSeverityIcon(severity: Insight['severity'], className: string = 'h-4 w-4') {
  switch (severity) {
    case 'alert':
      return <ShieldAlert className={className} />;
    case 'warning':
      return <Eye className={className} />;
    case 'info':
    default:
      return <Info className={className} />;
  }
}

function getConfidenceLabel(percent: number): { label: string; color: string; textColor: string } {
  if (percent >= 80) return { label: 'High confidence', color: 'bg-green-500', textColor: 'text-green-600 dark:text-green-400' };
  if (percent >= 60) return { label: 'Moderate confidence', color: 'bg-yellow-500', textColor: 'text-yellow-600 dark:text-yellow-400' };
  return { label: 'Low confidence', color: 'bg-red-500', textColor: 'text-red-600 dark:text-red-400' };
}

/** Generate a layman explanation for a specific insight type */
function getTypeExplanation(type: Insight['type']): string {
  switch (type) {
    case 'pattern':
      return 'A recurring price formation was identified. Traders use these patterns to anticipate where a stock price might move next, based on how similar formations played out historically.';
    case 'anomaly':
      return 'Something unusual happened in the market data. This could be a sudden spike in volume, an unexpected price move, or a statistical outlier that does not match recent behavior.';
    case 'sector':
      return 'A notable shift in how an entire industry group is performing. When a sector moves together, it often signals broader economic trends affecting all companies in that area.';
    case 'technical':
      return 'Technical indicators (mathematical calculations based on price, volume, or other data) are suggesting a potential move. These tools help identify whether a stock is overbought, oversold, or at a key decision point.';
    case 'economic':
      return 'An economic data release or macro event is relevant to market performance. Things like employment data, GDP, inflation reports, or central bank decisions fall into this category.';
    default:
      return 'A general market signal was detected.';
  }
}

/** Color scheme for each insight type section header */
function getTypeSectionColor(type: Insight['type']): { bg: string; text: string; border: string } {
  switch (type) {
    case 'pattern':
      return { bg: 'bg-emerald-500/10', text: 'text-emerald-700 dark:text-emerald-400', border: 'border-emerald-500/30' };
    case 'anomaly':
      return { bg: 'bg-orange-500/10', text: 'text-orange-700 dark:text-orange-400', border: 'border-orange-500/30' };
    case 'sector':
      return { bg: 'bg-purple-500/10', text: 'text-purple-700 dark:text-purple-400', border: 'border-purple-500/30' };
    case 'technical':
      return { bg: 'bg-sky-500/10', text: 'text-sky-700 dark:text-sky-400', border: 'border-sky-500/30' };
    case 'economic':
      return { bg: 'bg-amber-500/10', text: 'text-amber-700 dark:text-amber-400', border: 'border-amber-500/30' };
    default:
      return { bg: 'bg-gray-500/10', text: 'text-gray-700 dark:text-gray-400', border: 'border-gray-500/30' };
  }
}

/** Collapsible section component */
function DetailSection({
  title,
  icon,
  colorScheme,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  colorScheme: { bg: string; text: string; border: string };
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className={cn(
            'w-full justify-start gap-2 rounded-lg px-4 py-3 h-auto',
            colorScheme.bg,
            'border',
            colorScheme.border,
            'hover:opacity-90'
          )}
        >
          <span className={cn(colorScheme.text)}>{icon}</span>
          <span className={cn('font-semibold text-sm', colorScheme.text)}>{title}</span>
          <span className="ml-auto">
            {isOpen ? (
              <ChevronDown className={cn('h-4 w-4', colorScheme.text)} />
            ) : (
              <ChevronRight className={cn('h-4 w-4', colorScheme.text)} />
            )}
          </span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-3 pb-1 px-1">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function InsightDetail({ insight, open, onOpenChange }: InsightDetailProps) {
  const confidencePercent = insight.confidence ? Math.round(insight.confidence * 100) : null;
  const confidenceInfo = confidencePercent !== null ? getConfidenceLabel(confidencePercent) : null;
  const severityAction = getSeverityAction(insight.severity);
  const typeColor = getTypeSectionColor(insight.type);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto bg-card/95 backdrop-blur-sm">
        <DialogHeader>
          {/* Top badges row */}
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            {/* Action badge (colored pill) */}
            <Badge className={cn('gap-1 font-semibold text-sm px-3 py-1', severityAction.badgeBg, severityAction.badgeText)}>
              {getSeverityIcon(insight.severity, 'h-3.5 w-3.5')}
              {severityAction.label}
            </Badge>

            {/* Type badge */}
            <Badge variant="outline" className="gap-1">
              {getTypeIcon(insight.type, 'h-4 w-4')}
              {getInsightTypeLabel(insight.type)}
            </Badge>

            {/* Symbol */}
            {insight.symbol && (
              <Link
                href={`/stocks/${insight.symbol}`}
                className="inline-flex items-center gap-1 hover:underline"
              >
                <Badge variant="secondary" className="gap-1 font-mono font-bold text-sm px-2.5">
                  {insight.symbol}
                  <ExternalLink className="h-3 w-3" />
                </Badge>
              </Link>
            )}
          </div>

          <DialogTitle className="text-xl leading-snug">{insight.title}</DialogTitle>

          {/* Metadata row */}
          <div className="flex items-center gap-4 text-xs text-muted-foreground mt-1 flex-wrap">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {formatRelativeTime(insight.created_at)}
            </span>
            <span className="flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              {new Date(insight.created_at).toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
              })}
            </span>
            <span className="flex items-center gap-1">
              <Tag className="h-3 w-3" />
              {getInsightTypeLabel(insight.type)}
            </span>
          </div>
        </DialogHeader>

        <div className="space-y-5 mt-2">
          {/* Action explanation card */}
          <Card className={cn('border-l-4', severityAction.borderColor, 'bg-muted/40')}>
            <CardContent className="py-3 px-4">
              <div className="flex items-start gap-3">
                {getSeverityIcon(insight.severity, 'h-5 w-5 mt-0.5 shrink-0')}
                <div className="space-y-1">
                  <p className="text-sm font-medium">
                    Suggested Action: {severityAction.label}
                  </p>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {severityAction.explanation}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Confidence Section */}
          {confidencePercent !== null && confidenceInfo && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Gauge className="h-4 w-4 text-muted-foreground" />
                <h4 className="text-sm font-medium">Confidence Score</h4>
              </div>
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <div className="h-3 w-full bg-secondary rounded-full overflow-hidden">
                    <div
                      className={cn('h-full rounded-full transition-all duration-500', confidenceInfo.color)}
                      style={{ width: `${confidencePercent}%` }}
                    />
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <span className={cn('text-lg font-bold tabular-nums', confidenceInfo.textColor)}>
                    {confidencePercent}%
                  </span>
                </div>
              </div>
              <p className="text-xs text-muted-foreground italic">
                {confidenceInfo.label} -- {
                  confidencePercent >= 80
                    ? 'The analysis strongly supports this signal based on multiple data points.'
                    : confidencePercent >= 60
                      ? 'The analysis shows supporting evidence, but some uncertainty remains.'
                      : 'Limited supporting evidence. Consider gathering more information before acting.'
                }
              </p>
            </div>
          )}

          <Separator />

          {/* Analysis Type Section (collapsible) */}
          <DetailSection
            title={`${getInsightTypeLabel(insight.type)} Analysis`}
            icon={getTypeIcon(insight.type, 'h-4 w-4')}
            colorScheme={typeColor}
            defaultOpen={true}
          >
            <div className="space-y-3">
              {/* Technical finding */}
              <div>
                <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                  {insight.content || insight.description}
                </p>
              </div>

              {/* Layman explanation */}
              <Card className="bg-muted/30 border-dashed">
                <CardContent className="py-3 px-4">
                  <p className="text-xs font-medium text-muted-foreground mb-1">What does this mean?</p>
                  <p className="text-xs text-muted-foreground leading-relaxed italic">
                    {getTypeExplanation(insight.type)}
                  </p>
                </CardContent>
              </Card>
            </div>
          </DetailSection>

          {/* Supporting Data Section (collapsible) */}
          {insight.metadata && Object.keys(insight.metadata).length > 0 && (
            <DetailSection
              title="Supporting Data"
              icon={<Database className="h-4 w-4" />}
              colorScheme={{ bg: 'bg-slate-500/10', text: 'text-slate-700 dark:text-slate-400', border: 'border-slate-500/30' }}
              defaultOpen={false}
            >
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(insight.metadata).map(([key, value]) => (
                  <div key={key} className="rounded-lg bg-muted/40 px-3 py-2">
                    <dt className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-0.5">
                      {key.replace(/_/g, ' ')}
                    </dt>
                    <dd className="text-sm font-medium">
                      {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
                    </dd>
                  </div>
                ))}
              </div>
            </DetailSection>
          )}

          <Separator />

          {/* Annotations Section */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <MessageSquare className="h-4 w-4 text-muted-foreground" />
              <h4 className="text-sm font-medium">
                Annotations ({insight.annotations?.length || 0})
              </h4>
            </div>

            {/* Existing Annotations */}
            {insight.annotations && insight.annotations.length > 0 && (
              <div className="space-y-3 mb-4">
                {insight.annotations.map((annotation) => (
                  <Card key={annotation.id} className="bg-muted/30 border-dashed">
                    <CardContent className="pt-3 pb-2 px-4">
                      <p className="text-sm leading-relaxed">{annotation.note}</p>
                      <p className="text-xs text-muted-foreground mt-2">
                        {formatRelativeTime(annotation.created_at)}
                      </p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}

            {/* Add Annotation Form */}
            <AnnotationForm
              onSubmit={(note) => {
                // TODO: Integrate with annotation API using insight.id
                console.log('Add annotation to insight', insight.id, ':', note);
              }}
            />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
