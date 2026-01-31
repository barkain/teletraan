'use client';

import { useState, useRef, useCallback, useEffect, KeyboardEvent } from 'react';
import { Send, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface ChatInputProps {
  onSend: (message: string) => void;
  isLoading?: boolean;
  disabled?: boolean;
  placeholder?: string;
  maxLength?: number;
}

export function ChatInput({
  onSend,
  isLoading = false,
  disabled = false,
  placeholder = 'Ask about market data, stocks, or analysis...',
  maxLength = 2000,
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea based on content
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      const maxHeight = 200; // Max height before scrolling
      textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
    }
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (trimmed && !isLoading && !disabled) {
      onSend(trimmed);
      setValue('');
      // Reset height after sending
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  }, [value, isLoading, disabled, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Cmd/Ctrl + Enter to send
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        handleSend();
        return;
      }

      // Enter without shift to send (optional behavior)
      // Uncomment the following to enable sending on Enter:
      // if (e.key === 'Enter' && !e.shiftKey) {
      //   e.preventDefault();
      //   handleSend();
      // }
    },
    [handleSend]
  );

  const isOverLimit = value.length > maxLength;
  const canSend = value.trim().length > 0 && !isLoading && !disabled && !isOverLimit;

  return (
    <div className="relative flex flex-col bg-background border rounded-xl shadow-sm">
      {/* Textarea */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={isLoading || disabled}
        rows={1}
        className={cn(
          'w-full resize-none bg-transparent px-4 py-3 pr-14 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50',
          'min-h-[48px] max-h-[200px]',
          isOverLimit && 'text-destructive'
        )}
        aria-label="Chat input"
      />

      {/* Bottom bar with character count and send button */}
      <div className="flex items-center justify-between px-3 pb-2">
        {/* Character count */}
        <div
          className={cn(
            'text-xs',
            isOverLimit
              ? 'text-destructive'
              : value.length > maxLength * 0.9
              ? 'text-amber-500'
              : 'text-muted-foreground'
          )}
        >
          {value.length > 0 && (
            <span>
              {value.length}/{maxLength}
            </span>
          )}
        </div>

        {/* Keyboard shortcut hint */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground hidden sm:inline">
            <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">
              {typeof navigator !== 'undefined' && /Mac|iPhone/.test(navigator.platform) ? 'Cmd' : 'Ctrl'}
            </kbd>
            {' + '}
            <kbd className="px-1.5 py-0.5 bg-muted rounded text-[10px] font-mono">
              Enter
            </kbd>
            {' to send'}
          </span>

          {/* Send button */}
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  size="icon-sm"
                  onClick={handleSend}
                  disabled={!canSend}
                  className={cn(
                    'transition-all',
                    canSend
                      ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                      : 'bg-muted text-muted-foreground'
                  )}
                >
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>Send message</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>
    </div>
  );
}
