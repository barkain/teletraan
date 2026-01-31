'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, Wrench, Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import type { ToolCall } from '@/types/chat';

interface ToolCallDisplayProps {
  toolCall: ToolCall;
}

// Map tool names to human-readable descriptions
const toolDescriptions: Record<string, string> = {
  get_stock_data: 'Fetching stock data',
  get_sector_performance: 'Analyzing sector performance',
  scan_unusual_volume: 'Scanning for unusual volume',
  analyze_technicals: 'Running technical analysis',
  get_news_sentiment: 'Analyzing news sentiment',
  search_stocks: 'Searching stocks',
  get_market_overview: 'Getting market overview',
  calculate_indicators: 'Calculating indicators',
};

function getToolDescription(toolName: string): string {
  return toolDescriptions[toolName] || toolName.replace(/_/g, ' ');
}

function formatValue(value: unknown, indent = 0): string {
  if (value === null || value === undefined) {
    return 'null';
  }
  if (typeof value === 'string') {
    return `"${value}"`;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]';
    const items = value.map(v => formatValue(v, indent + 2));
    return `[\n${' '.repeat(indent + 2)}${items.join(',\n' + ' '.repeat(indent + 2))}\n${' '.repeat(indent)}]`;
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value);
    if (entries.length === 0) return '{}';
    const items = entries.map(
      ([k, v]) => `${' '.repeat(indent + 2)}"${k}": ${formatValue(v, indent + 2)}`
    );
    return `{\n${items.join(',\n')}\n${' '.repeat(indent)}}`;
  }
  return String(value);
}

export function ToolCallDisplay({ toolCall }: ToolCallDisplayProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const statusIcon = {
    pending: <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />,
    complete: <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />,
    error: <XCircle className="w-3.5 h-3.5 text-destructive" />,
  }[toolCall.status];

  const statusColor = {
    pending: 'border-muted-foreground/30',
    complete: 'border-green-500/30',
    error: 'border-destructive/30',
  }[toolCall.status];

  return (
    <div
      className={cn(
        'rounded-lg border bg-card text-sm overflow-hidden',
        statusColor
      )}
    >
      {/* Header - Always visible */}
      <Button
        variant="ghost"
        className="w-full justify-start gap-2 h-auto py-2 px-3 rounded-none hover:bg-muted/50"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />
        )}
        <Wrench className="w-4 h-4 text-muted-foreground flex-shrink-0" />
        <span className="flex-1 text-left font-medium">
          {getToolDescription(toolCall.name)}
        </span>
        {statusIcon}
      </Button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="border-t px-3 py-2 space-y-3 bg-muted/30">
          {/* Arguments */}
          <div>
            <div className="text-xs font-medium text-muted-foreground mb-1">
              Parameters
            </div>
            <pre className="text-xs font-mono bg-background rounded p-2 overflow-x-auto">
              {formatValue(toolCall.args)}
            </pre>
          </div>

          {/* Result (if available) */}
          {toolCall.status === 'complete' && toolCall.result !== undefined && (
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-1">
                Result
              </div>
              <pre className="text-xs font-mono bg-background rounded p-2 overflow-x-auto max-h-40 overflow-y-auto">
                {formatValue(toolCall.result)}
              </pre>
            </div>
          )}

          {/* Error (if any) */}
          {toolCall.status === 'error' && toolCall.error && (
            <div>
              <div className="text-xs font-medium text-destructive mb-1">
                Error
              </div>
              <pre className="text-xs font-mono bg-destructive/10 text-destructive rounded p-2 overflow-x-auto">
                {toolCall.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
