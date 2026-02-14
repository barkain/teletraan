'use client';

import React, { useMemo, useEffect, useRef } from 'react';
import { format, formatDistanceToNow } from 'date-fns';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
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

function getPhaseColor(phase: string): string {
  return PHASE_COLORS[phase] ?? 'bg-gray-100 text-gray-800 dark:bg-gray-900/60 dark:text-gray-300';
}

function getStatusIcon(status: string) {
  switch (status) {
    case 'running':
      return <Loader2 className="h-3.5 w-3.5 animate-spin text-yellow-500" />;
    case 'done':
      return <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />;
    case 'error':
      return <AlertCircle className="h-3.5 w-3.5 text-red-500" />;
    default:
      return null;
  }
}

interface ActivityEntryCardProps {
  entry: LLMActivityEntry;
  index: number;
}

function ActivityEntryCard({ entry, index }: ActivityEntryCardProps) {
  const [expandedPrompt, setExpandedPrompt] = React.useState(false);
  const [expandedResponse, setExpandedResponse] = React.useState(false);
  const relativeTime = formatDistanceToNow(new Date(entry.timestamp), { addSuffix: true });

  const handleCopyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(entry.prompt_preview);
    } catch {
      // Ignore error
    }
  };

  const handleCopyResponse = async () => {
    try {
      await navigator.clipboard.writeText(entry.response_preview);
    } catch {
      // Ignore error
    }
  };

  return (
    <div
      key={entry.seq}
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
          <p className="text-xs whitespace-pre-wrap font-mono break-words text-muted-foreground max-h-40 overflow-y-auto">
            {entry.prompt_preview}
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="mt-1 h-6 px-2 text-xs"
            onClick={handleCopyPrompt}
          >
            <Copy className="h-3 w-3 mr-1" />
            Copy
          </Button>
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
            <p className="text-xs whitespace-pre-wrap font-mono break-words text-muted-foreground max-h-40 overflow-y-auto">
              {entry.response_preview}
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="mt-1 h-6 px-2 text-xs"
              onClick={handleCopyResponse}
            >
              <Copy className="h-3 w-3 mr-1" />
              Copy
            </Button>
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
}

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

  // Show entries in reverse chronological order (newest first)
  const reversedEntries = useMemo(() => [...entries].reverse(), [entries]);

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
        {reversedEntries.map((entry, idx) => (
          <ActivityEntryCard key={entry.seq} entry={entry} index={idx} />
        ))}
      </div>
    </ScrollArea>
  );
}
