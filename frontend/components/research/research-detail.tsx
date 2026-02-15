'use client';

import { formatDistanceToNow, format } from 'date-fns';
import Link from 'next/link';
import {
  Clock,
  Play,
  CheckCircle,
  XCircle,
  ExternalLink,
  Loader2,
  AlertTriangle,
} from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { ResearchStatusBadge } from './research-status-badge';
import { ResearchTypeBadge } from './research-type-badge';
import { useResearchDetail, useCancelResearch } from '@/lib/hooks/use-research';
import type { FollowUpResearch } from '@/lib/types/research';

interface ResearchDetailProps {
  research: FollowUpResearch | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function TimelineItem({
  icon: Icon,
  label,
  time,
  active,
}: {
  icon: typeof Clock;
  label: string;
  time: string | null;
  active?: boolean;
}) {
  if (!time) return null;

  return (
    <div className="flex items-start gap-3">
      <div
        className={`mt-0.5 rounded-full p-1 ${
          active
            ? 'bg-blue-500/15 text-blue-600 dark:text-blue-400'
            : 'bg-muted text-muted-foreground'
        }`}
      >
        <Icon className={`h-3.5 w-3.5 ${active ? 'animate-spin' : ''}`} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-xs text-muted-foreground">
          {format(new Date(time), 'MMM d, yyyy HH:mm:ss')}
          {' '}({formatDistanceToNow(new Date(time), { addSuffix: true })})
        </p>
      </div>
    </div>
  );
}

export function ResearchDetail({
  research: initialResearch,
  open,
  onOpenChange,
}: ResearchDetailProps) {
  // Use detailed query for live updates (polling if active)
  const { data: detailedResearch } = useResearchDetail(
    open && initialResearch ? initialResearch.id : undefined
  );
  const research = detailedResearch || initialResearch;

  const cancelMutation = useCancelResearch();

  if (!research) return null;

  const symbols = (research.parameters?.symbols as string[]) || [];
  const questions = (research.parameters?.questions as string[]) || [];
  const canCancel = research.status === 'PENDING' || research.status === 'RUNNING';
  const isActive = research.status === 'RUNNING' || research.status === 'PENDING';

  const handleCancel = () => {
    cancelMutation.mutate(research.id, {
      onSuccess: () => {
        onOpenChange(false);
      },
    });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <div className="flex items-center gap-2 flex-wrap">
            <ResearchTypeBadge type={research.research_type} />
            <ResearchStatusBadge status={research.status} />
          </div>
          <SheetTitle className="text-left">{research.query}</SheetTitle>
          <SheetDescription className="text-left">
            Research #{research.id}
            {research.conversation_id && ` from conversation #${research.conversation_id}`}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-col gap-6 px-4 pb-4">
          {/* Parameters */}
          {(symbols.length > 0 || questions.length > 0) && (
            <div>
              <h3 className="text-sm font-semibold mb-3">Parameters</h3>
              {symbols.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs text-muted-foreground mb-1.5">Symbols</p>
                  <div className="flex flex-wrap gap-1.5">
                    {symbols.map((symbol) => (
                      <Badge key={symbol} variant="secondary">
                        {symbol}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {questions.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1.5">Questions</p>
                  <ul className="space-y-1">
                    {questions.map((q, i) => (
                      <li key={i} className="text-sm text-foreground">
                        {q}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <Separator />

          {/* Timeline */}
          <div>
            <h3 className="text-sm font-semibold mb-3">Timeline</h3>
            <div className="space-y-3">
              <TimelineItem
                icon={Clock}
                label="Created"
                time={research.created_at}
              />
              {research.status !== 'PENDING' && (
                <TimelineItem
                  icon={research.status === 'RUNNING' ? Loader2 : Play}
                  label="Started"
                  time={research.updated_at}
                  active={research.status === 'RUNNING'}
                />
              )}
              {research.completed_at && (
                <TimelineItem
                  icon={
                    research.status === 'COMPLETED'
                      ? CheckCircle
                      : research.status === 'FAILED'
                      ? XCircle
                      : CheckCircle
                  }
                  label={
                    research.status === 'COMPLETED'
                      ? 'Completed'
                      : research.status === 'FAILED'
                      ? 'Failed'
                      : 'Finished'
                  }
                  time={research.completed_at}
                />
              )}
            </div>
          </div>

          <Separator />

          {/* Result section */}
          {research.status === 'COMPLETED' && research.result_insight_id && (
            <div>
              <h3 className="text-sm font-semibold mb-3">Result</h3>
              {research.result_insight_summary && (
                <p className="text-sm text-muted-foreground mb-3">
                  {research.result_insight_summary}
                </p>
              )}
              <Button asChild variant="outline" size="sm">
                <Link href={`/insights?id=${research.result_insight_id}`}>
                  <ExternalLink className="h-4 w-4 mr-2" />
                  View Result Insight
                </Link>
              </Button>
            </div>
          )}

          {/* Error section */}
          {research.status === 'FAILED' && research.error_message && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-medium text-destructive">Research Failed</p>
                  <p className="text-sm text-destructive/80 mt-1">
                    {research.error_message}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Running indicator */}
          {isActive && (
            <div className="rounded-md border border-blue-200 bg-blue-500/10 dark:border-blue-800 p-4">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 text-blue-600 dark:text-blue-400 animate-spin" />
                <p className="text-sm text-blue-700 dark:text-blue-300">
                  {research.status === 'PENDING'
                    ? 'Waiting to start...'
                    : 'Research is running. Results will appear automatically.'}
                </p>
              </div>
            </div>
          )}

          {/* Cancel button */}
          {canCancel && (
            <Button
              variant="destructive"
              onClick={handleCancel}
              disabled={cancelMutation.isPending}
              className="w-full"
            >
              {cancelMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Cancelling...
                </>
              ) : (
                'Cancel Research'
              )}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
