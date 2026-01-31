'use client';

import { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Copy, Check, User, Bot } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { Message } from '@/types/chat';
import { ToolCallDisplay } from './tool-call-display';

interface MessageBubbleProps {
  message: Message;
}

// Simple markdown renderer for chat messages
function renderMarkdown(content: string): React.ReactNode {
  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeContent: string[] = [];
  let codeLanguage = '';
  let inTable = false;
  let tableRows: string[][] = [];

  const processInlineMarkdown = (text: string): React.ReactNode => {
    // Bold
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Inline code
    text = text.replace(/`([^`]+)`/g, '<code class="bg-muted px-1.5 py-0.5 rounded text-sm font-mono">$1</code>');
    // Links
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-primary underline hover:no-underline" target="_blank" rel="noopener noreferrer">$1</a>');

    return <span dangerouslySetInnerHTML={{ __html: text }} />;
  };

  lines.forEach((line, idx) => {
    // Code block handling
    if (line.startsWith('```')) {
      if (!inCodeBlock) {
        inCodeBlock = true;
        codeLanguage = line.slice(3).trim();
        codeContent = [];
      } else {
        inCodeBlock = false;
        elements.push(
          <pre key={`code-${idx}`} className="bg-muted rounded-md p-4 overflow-x-auto my-2">
            <code className="text-sm font-mono">{codeContent.join('\n')}</code>
          </pre>
        );
      }
      return;
    }

    if (inCodeBlock) {
      codeContent.push(line);
      return;
    }

    // Table handling
    if (line.startsWith('|')) {
      if (!inTable) {
        inTable = true;
        tableRows = [];
      }
      const cells = line.split('|').filter(c => c.trim() !== '');
      // Skip separator row
      if (!cells[0]?.match(/^[-:]+$/)) {
        tableRows.push(cells.map(c => c.trim()));
      }
      return;
    } else if (inTable && tableRows.length > 0) {
      // End of table
      inTable = false;
      elements.push(
        <div key={`table-${idx}`} className="overflow-x-auto my-2">
          <table className="min-w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-border">
                {tableRows[0]?.map((cell, i) => (
                  <th key={i} className="px-3 py-2 text-left font-semibold">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableRows.slice(1).map((row, rowIdx) => (
                <tr key={rowIdx} className="border-b border-border/50">
                  {row.map((cell, cellIdx) => (
                    <td key={cellIdx} className="px-3 py-2">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      tableRows = [];
    }

    // Empty line
    if (!line.trim()) {
      elements.push(<div key={`empty-${idx}`} className="h-2" />);
      return;
    }

    // Headers
    if (line.startsWith('### ')) {
      elements.push(
        <h4 key={`h4-${idx}`} className="font-semibold text-sm mt-3 mb-1">
          {processInlineMarkdown(line.slice(4))}
        </h4>
      );
      return;
    }
    if (line.startsWith('## ')) {
      elements.push(
        <h3 key={`h3-${idx}`} className="font-semibold mt-3 mb-1">
          {processInlineMarkdown(line.slice(3))}
        </h3>
      );
      return;
    }
    if (line.startsWith('# ')) {
      elements.push(
        <h2 key={`h2-${idx}`} className="font-bold text-lg mt-3 mb-1">
          {processInlineMarkdown(line.slice(2))}
        </h2>
      );
      return;
    }

    // List items
    if (line.match(/^[-*]\s/)) {
      elements.push(
        <li key={`li-${idx}`} className="ml-4 list-disc">
          {processInlineMarkdown(line.slice(2))}
        </li>
      );
      return;
    }
    if (line.match(/^\d+\.\s/)) {
      const content = line.replace(/^\d+\.\s/, '');
      elements.push(
        <li key={`li-${idx}`} className="ml-4 list-decimal">
          {processInlineMarkdown(content)}
        </li>
      );
      return;
    }

    // Regular paragraph
    elements.push(
      <p key={`p-${idx}`} className="leading-relaxed">
        {processInlineMarkdown(line)}
      </p>
    );
  });

  // Handle unclosed table at end
  if (inTable && tableRows.length > 0) {
    elements.push(
      <div key="table-final" className="overflow-x-auto my-2">
        <table className="min-w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-border">
              {tableRows[0]?.map((cell, i) => (
                <th key={i} className="px-3 py-2 text-left font-semibold">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableRows.slice(1).map((row, rowIdx) => (
              <tr key={rowIdx} className="border-b border-border/50">
                {row.map((cell, cellIdx) => (
                  <td key={cellIdx} className="px-3 py-2">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return <div className="space-y-1">{elements}</div>;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  return (
    <div
      className={cn(
        'flex gap-3 w-full',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
          isUser
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-muted-foreground'
        )}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      {/* Message content */}
      <div
        className={cn(
          'flex flex-col max-w-[80%]',
          isUser ? 'items-end' : 'items-start'
        )}
      >
        <div
          className={cn(
            'rounded-2xl px-4 py-3',
            isUser
              ? 'bg-primary text-primary-foreground rounded-tr-md'
              : 'bg-muted rounded-tl-md'
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              {renderMarkdown(message.content)}
            </div>
          )}
        </div>

        {/* Tool calls display */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mt-2 w-full">
            {message.toolCalls.map(toolCall => (
              <ToolCallDisplay key={toolCall.id} toolCall={toolCall} />
            ))}
          </div>
        )}

        {/* Footer with timestamp and actions */}
        <div
          className={cn(
            'flex items-center gap-2 mt-1 text-xs text-muted-foreground',
            isUser ? 'flex-row-reverse' : 'flex-row'
          )}
        >
          <span>
            {formatDistanceToNow(message.timestamp, { addSuffix: true })}
          </span>

          {/* Copy button for assistant messages */}
          {!isUser && (
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={handleCopy}
                    className="opacity-0 group-hover:opacity-100 hover:opacity-100 transition-opacity"
                  >
                    {copied ? (
                      <Check className="w-3 h-3 text-green-500" />
                    ) : (
                      <Copy className="w-3 h-3" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>{copied ? 'Copied!' : 'Copy message'}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </div>
      </div>
    </div>
  );
}
