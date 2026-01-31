'use client';

import { useEffect, useRef } from 'react';
import { useChat } from '@/lib/hooks/use-chat';
import { MessageBubble } from './message-bubble';
import { ChatInput } from './chat-input';
import { SuggestedPrompts } from './suggested-prompts';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { AlertCircle, Wifi, WifiOff } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ChatContainerProps {
  className?: string;
}

export function ChatContainer({ className }: ChatContainerProps) {
  const { messages, sendMessage, clearHistory, isConnected, isLoading, error } = useChat();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  return (
    <div className={cn("flex flex-col h-[calc(100vh-8rem)]", className)}>
      {/* Connection status */}
      <div className="flex items-center gap-2 px-4 py-2 border-b">
        {isConnected ? (
          <>
            <Wifi className="h-4 w-4 text-green-500" />
            <span className="text-sm text-muted-foreground">Connected</span>
          </>
        ) : (
          <>
            <WifiOff className="h-4 w-4 text-red-500" />
            <span className="text-sm text-muted-foreground">Disconnected</span>
          </>
        )}
        {messages.length > 0 && (
          <button
            onClick={clearHistory}
            className="ml-auto text-sm text-muted-foreground hover:text-foreground"
          >
            Clear history
          </button>
        )}
      </div>

      {/* Error display */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-destructive/10 text-destructive">
          <AlertCircle className="h-4 w-4" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* Messages area with ScrollArea */}
      <ScrollArea className="flex-1 p-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full">
            <h2 className="text-xl font-semibold mb-4">Market Analysis Assistant</h2>
            <p className="text-muted-foreground mb-6 text-center max-w-md">
              Ask me about stocks, market trends, technical analysis, or any investment-related questions.
            </p>
            <SuggestedPrompts onSelect={(prompt) => sendMessage({ content: prompt })} />
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {isLoading && (
              <div className="flex gap-2">
                <Skeleton className="h-4 w-4 rounded-full" />
                <Skeleton className="h-4 w-32" />
              </div>
            )}
            <div ref={scrollRef} />
          </div>
        )}
      </ScrollArea>

      {/* Input area */}
      <div className="border-t p-4">
        <ChatInput onSend={(message) => sendMessage({ content: message })} disabled={!isConnected || isLoading} />
      </div>
    </div>
  );
}
