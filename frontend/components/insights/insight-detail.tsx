'use client';

import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import {
  formatRelativeTime,
  getSeverityClasses,
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
  AlertCircle,
  ExternalLink,
  MessageSquare,
  Clock,
} from 'lucide-react';

interface InsightDetailProps {
  insight: Insight;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function getTypeIcon(type: Insight['type']) {
  const iconClass = 'h-5 w-5';
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
  const iconClass = 'h-4 w-4';
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

function getSeverityBadgeVariant(
  severity: Insight['severity']
): 'default' | 'secondary' | 'destructive' | 'outline' {
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

export function InsightDetail({ insight, open, onOpenChange }: InsightDetailProps) {
  const severityClasses = getSeverityClasses(insight.severity);
  const confidencePercent = insight.confidence ? Math.round(insight.confidence * 100) : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2 mb-2">
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
                className="inline-flex items-center gap-1 hover:underline"
              >
                <Badge variant="secondary" className="gap-1">
                  {insight.symbol}
                  <ExternalLink className="h-3 w-3" />
                </Badge>
              </Link>
            )}
          </div>
          <DialogTitle className="text-xl">{insight.title}</DialogTitle>
          <DialogDescription className="flex items-center gap-1 text-xs">
            <Clock className="h-3 w-3" />
            {formatRelativeTime(insight.created_at)}
          </DialogDescription>
        </DialogHeader>

        {/* Main Content */}
        <div className="space-y-6">
          {/* Description */}
          <div>
            <h4 className="text-sm font-medium mb-2">Description</h4>
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">
              {insight.content || insight.description}
            </p>
          </div>

          {/* Confidence Indicator */}
          {confidencePercent !== null && (
            <div>
              <h4 className="text-sm font-medium mb-2">Confidence Score</h4>
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <div className="h-2 w-full bg-secondary rounded-full overflow-hidden">
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
                <span className="text-sm font-medium w-12 text-right">{confidencePercent}%</span>
              </div>
            </div>
          )}

          {/* Metadata / Supporting Data */}
          {insight.metadata && Object.keys(insight.metadata).length > 0 && (
            <div>
              <h4 className="text-sm font-medium mb-2">Supporting Data</h4>
              <Card className="bg-muted/50">
                <CardContent className="pt-4">
                  <dl className="grid grid-cols-2 gap-2 text-sm">
                    {Object.entries(insight.metadata).map(([key, value]) => (
                      <div key={key} className="flex flex-col">
                        <dt className="text-muted-foreground capitalize">
                          {key.replace(/_/g, ' ')}
                        </dt>
                        <dd className="font-medium">
                          {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </CardContent>
              </Card>
            </div>
          )}

          <Separator />

          {/* Annotations Section */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <MessageSquare className="h-4 w-4" />
              <h4 className="text-sm font-medium">
                Annotations ({insight.annotations?.length || 0})
              </h4>
            </div>

            {/* Existing Annotations */}
            {insight.annotations && insight.annotations.length > 0 && (
              <div className="space-y-3 mb-4">
                {insight.annotations.map((annotation) => (
                  <Card key={annotation.id} className="bg-muted/30">
                    <CardContent className="pt-4 pb-3">
                      <p className="text-sm">{annotation.note}</p>
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
