'use client';

import React, { useMemo, useEffect, useRef, useState, useCallback } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Loader2,
  Copy,
  ChevronUp,
} from 'lucide-react';
import type { LLMActivityEntry } from '@/lib/hooks/use-analysis-task';
import { Button } from '@/components/ui/button';

const PHASE_COLORS: Record<string, string> = {
  macro_scan: 'bg-blue-100 text-blue-800 dark:bg-blue-900/60 dark:text-blue-300',
  sector_rotation: 'bg-purple-100 text-purple-800 dark:bg-purple-900/60 dark:text-purple-300',
  opportunity_hunt: 'bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-300',
  heatmap_analysis: 'bg-orange-100 text-orange-800 dark:bg-orange-900/60 dark:text-orange-300',
  coverage_evaluation: 'bg-pink-100 text-pink-800 dark:bg-pink-900/60 dark:text-pink-300',
  deep_dive: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/60 dark:text-indigo-300',
  synthesis: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900/60 dark:text-cyan-300',
};

/** Maximum characters to show before truncation in prompt/response previews. */
const CONTENT_TRUNCATE_LIMIT = 500;

function getPhaseColor(phase: string): string {
  return PHASE_COLORS[phase] ?? 'bg-gray-100 text-gray-800 dark:bg-gray-900/60 dark:text-gray-300';
}

function getStatusIcon(status: string, className?: string) {
  const cls = className ?? 'h-3.5 w-3.5';
  switch (status) {
    case 'running':
      return <Loader2 className={`${cls} animate-spin text-yellow-500`} />;
    case 'done':
      return <CheckCircle2 className={`${cls} text-green-500`} />;
    case 'error':
      return <AlertCircle className={`${cls} text-red-500`} />;
    default:
      return null;
  }
}

/** Renders a truncated text block with an expand/collapse toggle. */
function TruncatedText({
  text,
  limit,
  onCopy,
}: {
  text: string;
  limit: number;
  onCopy: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isTruncated = text.length > limit;
  const displayText = isTruncated && !expanded ? text.slice(0, limit) + '...' : text;

  return (
    <>
      <p className="text-xs whitespace-pre-wrap font-mono break-words text-muted-foreground max-h-40 overflow-y-auto">
        {displayText}
      </p>
      <div className="flex items-center gap-1 mt-1">
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={onCopy}
        >
          <Copy className="h-3 w-3 mr-1" />
          Copy
        </Button>
        {isTruncated && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={() => setExpanded((prev) => !prev)}
          >
            {expanded ? 'Show less' : `Show all (${text.length} chars)`}
          </Button>
        )}
      </div>
    </>
  );
}

interface ActivityEntryCardProps {
  entry: LLMActivityEntry;
  index: number;
}

const ActivityEntryCard = React.memo(function ActivityEntryCard({ entry, index }: ActivityEntryCardProps) {
  const [expandedPrompt, setExpandedPrompt] = useState(false);
  const [expandedResponse, setExpandedResponse] = useState(false);
  const relativeTime = formatDistanceToNow(new Date(entry.timestamp), { addSuffix: true });

  const handleCopyPrompt = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(entry.prompt_preview);
    } catch {
      // Ignore error
    }
  }, [entry.prompt_preview]);

  const handleCopyResponse = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(entry.response_preview);
    } catch {
      // Ignore error
    }
  }, [entry.response_preview]);

  return (
    <div
      className={`border rounded-lg p-3 space-y-2 transition-all ${
        index % 2 === 0 ? 'bg-muted/40' : 'bg-background'
      } ${entry.status === 'running' ? 'border-primary/50 animate-pulse' : 'border-border/50'}`}
    >
      {/* Header: Phase, Agent, Status, Time */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Badge variant="secondary" className={`text-xs ${getPhaseColor(entry.phase)}`}>
            {entry.phase.replace(/_/g, ' ')}
          </Badge>
          {entry.symbol && (
            <Badge variant="outline" className="text-xs font-bold">
              {entry.symbol}
            </Badge>
          )}
          <span className="text-xs font-medium text-muted-foreground truncate">
            {entry.agent_name}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {getStatusIcon(entry.status)}
          <span className="text-xs text-muted-foreground">{relativeTime}</span>
        </div>
      </div>

      {/* Prompt Preview */}
      <Collapsible open={expandedPrompt} onOpenChange={setExpandedPrompt}>
        <CollapsibleTrigger className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground">
          {expandedPrompt ? (
            <ChevronUp className="h-3 w-3" />
          ) : (
            <ChevronDown className="h-3 w-3" />
          )}
          Input
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 p-2 bg-muted/30 rounded border border-border/50">
          <TruncatedText
            text={entry.prompt_preview}
            limit={CONTENT_TRUNCATE_LIMIT}
            onCopy={handleCopyPrompt}
          />
        </CollapsibleContent>
      </Collapsible>

      {/* Response Preview */}
      {entry.response_preview && (
        <Collapsible open={expandedResponse} onOpenChange={setExpandedResponse}>
          <CollapsibleTrigger className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            {expandedResponse ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            Output
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 p-2 bg-muted/30 rounded border border-border/50">
            <TruncatedText
              text={entry.response_preview}
              limit={CONTENT_TRUNCATE_LIMIT}
              onCopy={handleCopyResponse}
            />
          </CollapsibleContent>
        </Collapsible>
      )}

      {/* Metrics Footer */}
      <div className="flex items-center justify-between text-xs text-muted-foreground pt-1 border-t border-border/50">
        <div className="space-x-2">
          <span>
            Tokens: <span className="font-mono">{entry.input_tokens}</span> in,{' '}
            <span className="font-mono">{entry.output_tokens}</span> out
          </span>
        </div>
        <span className="font-mono">{Math.round(entry.duration_ms)}ms</span>
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Segmented progress bar for deep dive — one compact row per symbol
// ---------------------------------------------------------------------------

/** Fixed analyst order for the segmented bar. */
const ANALYST_ORDER = ['technical', 'sector', 'macro', 'correlation', 'risk'] as const;

/** Short display labels for each analyst. */
const ANALYST_LABELS: Record<string, string> = {
  technical: 'Tech',
  sector: 'Sector',
  macro: 'Macro',
  correlation: 'Corr',
  risk: 'Risk',
};

/** Segment color classes by status. */
function getSegmentClasses(status: 'running' | 'done' | 'error' | 'pending'): string {
  switch (status) {
    case 'running':
      return 'bg-amber-400 dark:bg-amber-500 animate-pulse';
    case 'done':
      return 'bg-green-500 dark:bg-green-500';
    case 'error':
      return 'bg-red-500 dark:bg-red-500';
    case 'pending':
    default:
      return 'bg-muted-foreground/20 dark:bg-muted-foreground/20';
  }
}

interface SymbolGroup {
  symbol: string;
  entries: LLMActivityEntry[];
}

interface SymbolProgressBarProps {
  symbol: string;
  entries: LLMActivityEntry[];
}

const SymbolProgressBar = React.memo(function SymbolProgressBar({ symbol, entries }: SymbolProgressBarProps) {
  const [expandedAnalyst, setExpandedAnalyst] = useState<string | null>(null);

  // Build a map from analyst name → entry for quick lookup.
  // The agent_name field may contain suffixes (e.g. "technical_analyst"),
  // so we match against the ANALYST_ORDER prefix.
  const entryByAnalyst = useMemo(() => {
    const map = new Map<string, LLMActivityEntry>();
    for (const entry of entries) {
      const name = entry.agent_name.toLowerCase();
      for (const analyst of ANALYST_ORDER) {
        if (name.includes(analyst) && !map.has(analyst)) {
          map.set(analyst, entry);
          break;
        }
      }
    }
    return map;
  }, [entries]);

  // Aggregate stats
  const totalTokens = entries.reduce((sum, e) => sum + e.input_tokens + e.output_tokens, 0);
  const totalDurationMs = entries.reduce((sum, e) => sum + e.duration_ms, 0);
  const hasRunning = entries.some((e) => e.status === 'running');

  // Format duration
  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  // Handle segment click — toggle expand
  const handleSegmentClick = useCallback((analyst: string) => {
    setExpandedAnalyst((prev) => (prev === analyst ? null : analyst));
  }, []);

  // Find the entry for the expanded analyst
  const expandedEntry = expandedAnalyst ? entryByAnalyst.get(expandedAnalyst) : null;

  return (
    <div
      className={`border rounded-lg overflow-hidden transition-all ${
        hasRunning ? 'border-amber-400/60' : 'border-border/50'
      }`}
    >
      {/* Compact row: symbol + segmented bar + aggregate stats */}
      <div className="flex items-center gap-3 px-3 py-2 h-[44px]">
        {/* Symbol label */}
        <span className="text-sm font-bold text-foreground w-14 shrink-0 truncate">
          {symbol}
        </span>

        {/* Segmented progress bar */}
        <div className="flex-1 flex items-center gap-0.5 h-6">
          {ANALYST_ORDER.map((analyst) => {
            const entry = entryByAnalyst.get(analyst);
            const status = entry?.status ?? 'pending';
            const isSelected = expandedAnalyst === analyst;

            return (
              <Tooltip key={analyst}>
                <TooltipTrigger asChild>
                  <button
                    className={`
                      relative flex-1 h-full rounded-sm transition-all cursor-pointer
                      ${getSegmentClasses(status)}
                      ${isSelected ? 'ring-2 ring-foreground/50 ring-offset-1 ring-offset-background scale-y-110' : ''}
                      ${status !== 'pending' ? 'hover:brightness-110' : ''}
                    `}
                    onClick={() => entry && handleSegmentClick(analyst)}
                    disabled={!entry}
                    aria-label={`${ANALYST_LABELS[analyst]} analyst: ${status}`}
                  >
                    {/* Show abbreviated label inside segment */}
                    <span className={`
                      absolute inset-0 flex items-center justify-center text-[9px] font-semibold leading-none
                      ${status === 'done' || status === 'running' || status === 'error'
                        ? 'text-white dark:text-white'
                        : 'text-muted-foreground/60'}
                    `}>
                      {ANALYST_LABELS[analyst]}
                    </span>
                  </button>
                </TooltipTrigger>
                {entry && (
                  <TooltipContent side="top" className="text-xs space-y-0.5">
                    <div className="font-semibold">{entry.agent_name}</div>
                    <div>Status: {status}</div>
                    {entry.input_tokens + entry.output_tokens > 0 && (
                      <div>Tokens: {entry.input_tokens} in / {entry.output_tokens} out</div>
                    )}
                    {entry.duration_ms > 0 && (
                      <div>Duration: {formatDuration(entry.duration_ms)}</div>
                    )}
                  </TooltipContent>
                )}
              </Tooltip>
            );
          })}
        </div>

        {/* Aggregate stats */}
        <div className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground font-mono">
          {totalTokens > 0 && <span>{totalTokens} tok</span>}
          {totalDurationMs > 0 && <span>{formatDuration(totalDurationMs)}</span>}
        </div>
      </div>

      {/* Expanded detail: shows the selected analyst's full ActivityEntryCard */}
      {expandedEntry && (
        <div className="border-t border-border/50 bg-muted/20 px-2 py-2 relative">
          <Button
            variant="ghost"
            size="sm"
            className="absolute top-1 right-1 h-5 w-5 p-0 z-10"
            onClick={() => setExpandedAnalyst(null)}
            title="Collapse"
          >
            <ChevronUp className="h-3 w-3" />
          </Button>
          <ActivityEntryCard entry={expandedEntry} index={0} />
        </div>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Types for the merged feed
// ---------------------------------------------------------------------------

type FeedItem =
  | { kind: 'entry'; entry: LLMActivityEntry }
  | { kind: 'deep_dive_group'; group: SymbolGroup };

// ---------------------------------------------------------------------------
// Main feed component
// ---------------------------------------------------------------------------

interface LLMActivityFeedProps {
  entries: LLMActivityEntry[];
}

export function LLMActivityFeed({ entries }: LLMActivityFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new entries appear
  useEffect(() => {
    if (scrollRef.current) {
      const scrollElement = scrollRef.current.querySelector('[data-radix-scroll-area-viewport]');
      if (scrollElement) {
        setTimeout(() => {
          scrollElement.scrollTop = scrollElement.scrollHeight;
        }, 0);
      }
    }
  }, [entries.length]);

  // Build merged feed: non-deep_dive entries as individual cards,
  // deep_dive entries grouped by symbol. Groups are placed at the
  // position of the *first* entry for that symbol (chronologically).
  const feedItems: FeedItem[] = useMemo(() => {
    // Separate deep_dive from other entries
    const deepDiveEntries: LLMActivityEntry[] = [];
    const otherEntries: LLMActivityEntry[] = [];
    for (const e of entries) {
      if (e.phase === 'deep_dive' && e.symbol) {
        deepDiveEntries.push(e);
      } else {
        otherEntries.push(e);
      }
    }

    // Group deep_dive by symbol, preserving insertion order
    const symbolGroupMap = new Map<string, LLMActivityEntry[]>();
    for (const e of deepDiveEntries) {
      let group = symbolGroupMap.get(e.symbol);
      if (!group) {
        group = [];
        symbolGroupMap.set(e.symbol, group);
      }
      group.push(e);
    }

    // Find the minimum seq per symbol group (used to position the group in the feed)
    const symbolMinSeq = new Map<string, number>();
    for (const [sym, group] of symbolGroupMap) {
      symbolMinSeq.set(sym, Math.min(...group.map((e) => e.seq)));
    }

    // Build a combined list: other entries + one placeholder per group, sorted by seq
    type SortableItem =
      | { kind: 'entry'; seq: number; entry: LLMActivityEntry }
      | { kind: 'group'; seq: number; symbol: string; entries: LLMActivityEntry[] };

    const items: SortableItem[] = otherEntries.map((e) => ({ kind: 'entry' as const, seq: e.seq, entry: e }));
    for (const [sym, group] of symbolGroupMap) {
      items.push({ kind: 'group' as const, seq: symbolMinSeq.get(sym)!, symbol: sym, entries: group });
    }

    // Sort by seq ascending (chronological)
    items.sort((a, b) => a.seq - b.seq);

    // Reverse for newest-first display
    items.reverse();

    return items.map((item): FeedItem => {
      if (item.kind === 'entry') {
        return { kind: 'entry', entry: item.entry };
      }
      return { kind: 'deep_dive_group', group: { symbol: item.symbol, entries: item.entries } };
    });
  }, [entries]);

  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
        Waiting for LLM activity...
      </div>
    );
  }

  return (
    <ScrollArea className="h-[400px] w-full border border-border/50 rounded-lg bg-card/80">
      <div ref={scrollRef} className="p-3 space-y-2">
        {feedItems.map((item, idx) => {
          if (item.kind === 'entry') {
            return (
              <ActivityEntryCard
                key={`entry-${item.entry.seq}`}
                entry={item.entry}
                index={idx}
              />
            );
          }
          return (
            <SymbolProgressBar
              key={`group-${item.group.symbol}`}
              symbol={item.group.symbol}
              entries={item.group.entries}
            />
          );
        })}
      </div>
    </ScrollArea>
  );
}
