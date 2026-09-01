'use client';

import { History } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ActionBaseRate } from '@/types';

/**
 * The measured hit rate for an action type, shown where a stated confidence
 * percentage used to be.
 *
 * Three states, and the difference between them is the whole point:
 *
 * - **unknown** (`record` is null) -- the rates have not loaded. Renders
 *   nothing, because an empty space is honest and a zero is not.
 * - **unmeasured** (`record.rate` is null) -- fewer graded outcomes than the
 *   API's `min_sample`. Renders "too few graded" plus n, never a number.
 * - **measured** -- renders the rate, the sample size, and a caption naming the
 *   action, so it cannot be read as a probability for the idea on screen.
 *
 * The caption and the `n=` are not decoration. A bare "35%" next to a BUY badge
 * is indistinguishable from the confidence figure this replaced.
 */
export function TrackRecordBadge({
  record,
  size = 'md',
  className,
}: {
  record: ActionBaseRate | null | undefined;
  size?: 'sm' | 'md';
  className?: string;
}) {
  if (!record) return null;

  const title = `${record.headline} ${record.caveat}`;
  const small = size === 'sm';

  if (record.percent === null) {
    return (
      <div
        className={cn('flex items-center gap-1.5 text-muted-foreground', className)}
        title={title}
      >
        <History className={small ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
        <span className={small ? 'text-[10px]' : 'text-xs'}>
          Too few graded {record.action} calls (n={record.graded})
        </span>
      </div>
    );
  }

  return (
    <div className={cn('flex items-center gap-2', className)} title={title}>
      <History className={cn('text-muted-foreground', small ? 'h-3 w-3' : 'h-3.5 w-3.5')} />
      <div className="flex flex-col items-start gap-0.5">
        <div className="flex items-baseline gap-1.5">
          <span
            className={cn(
              'font-semibold tabular-nums',
              small ? 'text-xs' : 'text-sm',
            )}
          >
            {record.percent}%
          </span>
          <span className="text-[10px] text-muted-foreground tabular-nums">
            n={record.graded}
          </span>
        </div>
        <span className="text-[10px] text-muted-foreground leading-none">
          of past {record.action} calls worked
        </span>
      </div>
    </div>
  );
}

/**
 * The same record as one line of prose, for detail views and summaries.
 */
export function TrackRecordLine({
  record,
  className,
}: {
  record: ActionBaseRate | null | undefined;
  className?: string;
}) {
  if (!record) return null;
  return (
    <p className={cn('text-xs text-muted-foreground', className)}>
      <span className="font-medium text-foreground">{record.headline}</span>{' '}
      {record.caveat}
    </p>
  );
}

/**
 * Shown where an insight has a stated confidence but no graded record exists for
 * it at all -- the basic (non-deep) insights, which nothing ever tracks.
 *
 * Saying "not tracked" is the honest replacement for a confidence bar. Inventing
 * a rate for them, or borrowing the deep insights' rate, would both be claims
 * the record does not support.
 */
export function UntrackedNotice({ className }: { className?: string }) {
  return (
    <div
      className={cn('flex items-center gap-1.5 text-muted-foreground', className)}
      title="These signals are not outcome-tracked, so there is no measured hit rate for them."
    >
      <History className="h-3 w-3" />
      <span className="text-[10px] leading-none">No track record</span>
    </div>
  );
}
