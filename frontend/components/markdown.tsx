'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

interface MarkdownProps {
  children: string;
  className?: string;
}

/**
 * Renders LLM-generated markdown (discovery summaries, theses) with
 * styling matched to the app's typography. Supports GFM tables/lists.
 */
export function Markdown({ children, className }: MarkdownProps) {
  return (
    <div className={cn('text-sm leading-relaxed space-y-3', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h2 className="text-base font-semibold mt-4 first:mt-0">{children}</h2>
          ),
          h2: ({ children }) => (
            <h2 className="text-base font-semibold mt-4 first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-semibold mt-3 first:mt-0">{children}</h3>
          ),
          p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-foreground">{children}</strong>
          ),
          ul: ({ children }) => (
            <ul className="my-2 ml-4 list-disc space-y-1 marker:text-muted-foreground">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="my-2 ml-4 list-decimal space-y-1 marker:text-muted-foreground">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          code: ({ children }) => (
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{children}</code>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border px-2 py-1 text-left font-semibold">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border border-border px-2 py-1">{children}</td>
          ),
          hr: () => <hr className="my-3 border-border" />,
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-border pl-3 text-muted-foreground">
              {children}
            </blockquote>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-2"
            >
              {children}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
