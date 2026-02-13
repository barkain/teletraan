'use client';

import { useEffect, useRef, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import {
  User,
  Bot,
  Wifi,
  WifiOff,
  AlertCircle,
  Check,
  X,
  Rocket,
  ArrowRight,
  Loader2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { ChatInput } from '@/components/chat/chat-input';
import { renderMarkdown } from '@/components/chat/message-bubble';
import { postApi } from '@/lib/api';
import {
  useInsightChat,
  useInsightConversation,
  type ChatMessage,
  type ModificationProposal,
  type ResearchRequest,
} from '@/lib/hooks/use-insight-conversation';

// ============================================
// Types
// ============================================

interface InsightConversationPanelProps {
  conversationId: number;
  insightId: number;
  onModificationApplied?: () => void;
  onResearchLaunched?: (researchId: number) => void;
}

interface ModificationResponse {
  success: boolean;
  message: string;
  insight_id: number;
}

interface ResearchResponse {
  research_id: number;
  status: string;
  message: string;
}

// ============================================
// Helper Components
// ============================================

function ConnectionStatusBadge({
  isConnected,
  isError,
}: {
  isConnected: boolean;
  isError?: boolean;
}) {
  if (isError) {
    return (
      <Badge variant="destructive" className="gap-1">
        <AlertCircle className="h-3 w-3" />
        Error
      </Badge>
    );
  }

  if (isConnected) {
    return (
      <Badge variant="default" className="gap-1 bg-green-600 hover:bg-green-600">
        <Wifi className="h-3 w-3" />
        Connected
      </Badge>
    );
  }

  return (
    <Badge variant="secondary" className="gap-1">
      <WifiOff className="h-3 w-3" />
      Disconnected
    </Badge>
  );
}

function MessageAvatar({ role }: { role: 'user' | 'assistant' }) {
  return (
    <Avatar size="sm">
      <AvatarFallback
        className={cn(
          role === 'user'
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-muted-foreground'
        )}
      >
        {role === 'user' ? (
          <User className="h-3 w-3" />
        ) : (
          <Bot className="h-3 w-3" />
        )}
      </AvatarFallback>
    </Avatar>
  );
}

function StreamingIndicator() {
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground">
      <span className="animate-pulse">Thinking</span>
      <span className="flex gap-0.5">
        <span
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce"
          style={{ animationDelay: '0ms' }}
        />
        <span
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce"
          style={{ animationDelay: '150ms' }}
        />
        <span
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce"
          style={{ animationDelay: '300ms' }}
        />
      </span>
    </span>
  );
}

// ============================================
// Modification Proposal Card
// ============================================

function ModificationProposalCard({
  proposal,
  insightId: _insightId,
  onApprove,
  onReject,
  isProcessing,
}: {
  proposal: ModificationProposal;
  insightId: number;
  onApprove: () => void;
  onReject: () => void;
  isProcessing: boolean;
}) {
  const formatValue = (value: unknown): string => {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    return String(value);
  };

  return (
    <Card className="mt-3 border-amber-500/50 bg-amber-500/5">
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <ArrowRight className="h-4 w-4 text-amber-500" />
          Proposed Modification
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className="space-y-3">
          <div>
            <span className="text-xs font-medium text-muted-foreground">Field:</span>
            <p className="text-sm font-mono bg-muted px-2 py-1 rounded mt-1">
              {proposal.field}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <span className="text-xs font-medium text-muted-foreground">
                Current Value:
              </span>
              <pre className="text-xs bg-muted px-2 py-1 rounded mt-1 overflow-x-auto max-h-20">
                {formatValue(proposal.old_value)}
              </pre>
            </div>
            <div>
              <span className="text-xs font-medium text-muted-foreground">
                New Value:
              </span>
              <pre className="text-xs bg-green-500/10 px-2 py-1 rounded mt-1 overflow-x-auto max-h-20 border border-green-500/20">
                {formatValue(proposal.new_value)}
              </pre>
            </div>
          </div>

          <div>
            <span className="text-xs font-medium text-muted-foreground">Reasoning:</span>
            <p className="text-sm text-muted-foreground mt-1">{proposal.reasoning}</p>
          </div>

          <div className="flex gap-2 pt-2">
            <Button
              size="sm"
              onClick={onApprove}
              disabled={isProcessing}
              className="gap-1"
            >
              {isProcessing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Check className="h-3 w-3" />
              )}
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={onReject}
              disabled={isProcessing}
              className="gap-1"
            >
              <X className="h-3 w-3" />
              Reject
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ============================================
// Research Request Card
// ============================================

function ResearchRequestCard({
  research,
  insightId: _insightId,
  onLaunch,
  isProcessing,
}: {
  research: ResearchRequest;
  insightId: number;
  onLaunch: () => void;
  isProcessing: boolean;
}) {
  return (
    <Card className="mt-3 border-blue-500/50 bg-blue-500/5">
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Rocket className="h-4 w-4 text-blue-500" />
          Research Request
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className="space-y-3">
          <div>
            <span className="text-xs font-medium text-muted-foreground">Focus Area:</span>
            <p className="text-sm mt-1">{research.focus_area}</p>
          </div>

          {research.specific_questions.length > 0 && (
            <div>
              <span className="text-xs font-medium text-muted-foreground">
                Questions to Investigate:
              </span>
              <ul className="text-sm mt-1 space-y-1">
                {research.specific_questions.map((question, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="text-muted-foreground">{idx + 1}.</span>
                    <span>{question}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {research.related_symbols.length > 0 && (
            <div>
              <span className="text-xs font-medium text-muted-foreground">
                Related Symbols:
              </span>
              <div className="flex flex-wrap gap-1 mt-1">
                {research.related_symbols.map((symbol) => (
                  <Badge key={symbol} variant="secondary">
                    {symbol}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <div className="pt-2">
            <Button
              size="sm"
              onClick={onLaunch}
              disabled={isProcessing}
              className="gap-1"
            >
              {isProcessing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Rocket className="h-3 w-3" />
              )}
              Launch Research
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ============================================
// Message Bubble
// ============================================

function ConversationMessageBubble({
  message,
  insightId,
  onModificationApplied,
  onResearchLaunched,
}: {
  message: ChatMessage;
  insightId: number;
  onModificationApplied?: () => void;
  onResearchLaunched?: (researchId: number) => void;
}) {
  const [isProcessing, setIsProcessing] = useState(false);
  const isUser = message.role === 'user';

  const handleApproveModification = async () => {
    if (!message.modification) return;

    setIsProcessing(true);
    try {
      const response = await postApi<ModificationResponse>(
        `/api/v1/insights/${insightId}/modifications`,
        {
          action: 'approve',
          field: message.modification.field,
          new_value: message.modification.new_value,
        }
      );
      if (response.success) {
        onModificationApplied?.();
      }
    } catch (error) {
      console.error('Failed to approve modification:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleRejectModification = async () => {
    if (!message.modification) return;

    setIsProcessing(true);
    try {
      await postApi<ModificationResponse>(
        `/api/v1/insights/${insightId}/modifications`,
        {
          action: 'reject',
          field: message.modification.field,
        }
      );
    } catch (error) {
      console.error('Failed to reject modification:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleLaunchResearch = async () => {
    if (!message.research) return;

    setIsProcessing(true);
    try {
      const response = await postApi<ResearchResponse>(
        `/api/v1/insights/${insightId}/research`,
        {
          focus_area: message.research.focus_area,
          specific_questions: message.research.specific_questions,
          related_symbols: message.research.related_symbols,
        }
      );
      if (response.research_id) {
        onResearchLaunched?.(response.research_id);
      }
    } catch (error) {
      console.error('Failed to launch research:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div
      className={cn(
        'flex gap-3 w-full',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      <MessageAvatar role={message.role} />

      <div
        className={cn(
          'flex flex-col overflow-hidden',
          isUser ? 'max-w-[85%] items-end' : 'max-w-[75%] items-start'
        )}
      >
        <div
          className={cn(
            'rounded-2xl px-4 py-3 overflow-hidden',
            isUser
              ? 'bg-primary text-primary-foreground rounded-tr-sm'
              : 'bg-muted rounded-tl-sm'
          )}
        >
          {message.isStreaming && !message.content ? (
            <StreamingIndicator />
          ) : isUser ? (
            <p className="text-sm whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{message.content}</p>
          ) : (
            <div className="text-sm prose prose-sm dark:prose-invert max-w-none [&>*]:my-0.5 [&>h2]:mt-2 [&>h3]:mt-2 [&>h4]:mt-2 [&>pre]:my-1.5 break-words [overflow-wrap:anywhere]">
              {renderMarkdown(message.content)}
            </div>
          )}
        </div>

        {/* Modification Proposal */}
        {message.modification && !isUser && (
          <ModificationProposalCard
            proposal={message.modification}
            insightId={insightId}
            onApprove={handleApproveModification}
            onReject={handleRejectModification}
            isProcessing={isProcessing}
          />
        )}

        {/* Research Request */}
        {message.research && !isUser && (
          <ResearchRequestCard
            research={message.research}
            insightId={insightId}
            onLaunch={handleLaunchResearch}
            isProcessing={isProcessing}
          />
        )}

        {/* Timestamp */}
        <span
          className={cn(
            'text-xs text-muted-foreground mt-1',
            isUser ? 'text-right' : 'text-left'
          )}
        >
          {formatDistanceToNow(message.timestamp, { addSuffix: true })}
        </span>
      </div>
    </div>
  );
}

// ============================================
// Loading Skeleton
// ============================================

function MessagesSkeleton() {
  return (
    <div className="space-y-4 p-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className={cn('flex gap-3', i % 2 === 0 && 'flex-row-reverse')}>
          <Skeleton className="h-6 w-6 rounded-full" />
          <div className={cn('space-y-2', i % 2 === 0 && 'items-end')}>
            <Skeleton className="h-16 w-48 rounded-2xl" />
            <Skeleton className="h-3 w-20" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ============================================
// Main Component
// ============================================

export function InsightConversationPanel({
  conversationId,
  insightId,
  onModificationApplied,
  onResearchLaunched,
}: InsightConversationPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Fetch conversation details
  const {
    conversation,
    messages: conversationMessages,
    isLoading: isLoadingConversation,
  } = useInsightConversation(conversationId);

  // WebSocket chat hook
  const {
    connectionState,
    isConnected,
    messages,
    isLoading: isSending,
    error,
    sendMessage,
    loadInitialMessages,
  } = useInsightChat(conversationId);

  // Load initial messages from conversation
  useEffect(() => {
    if (conversationMessages.length > 0 && messages.length === 0) {
      loadInitialMessages(conversationMessages);
    }
  }, [conversationMessages, messages.length, loadInitialMessages]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const isError = connectionState === 'error';

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-3">
          <h3 className="font-medium">
            {conversation?.title || 'Conversation'}
          </h3>
        </div>
        <ConnectionStatusBadge isConnected={isConnected} isError={isError} />
      </div>

      {/* Error display */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-destructive/10 text-destructive">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* Messages area */}
      <ScrollArea className="flex-1 min-h-0">
        {isLoadingConversation ? (
          <MessagesSkeleton />
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full p-6 text-center">
            <Bot className="h-12 w-12 text-muted-foreground mb-4" />
            <h4 className="text-lg font-medium mb-2">Start a Conversation</h4>
            <p className="text-sm text-muted-foreground max-w-md">
              Ask questions about this insight, request modifications, or
              explore related research topics.
            </p>
          </div>
        ) : (
          <div className="space-y-4 p-4">
            {messages.map((message) => (
              <ConversationMessageBubble
                key={message.id}
                message={message}
                insightId={insightId}
                onModificationApplied={onModificationApplied}
                onResearchLaunched={onResearchLaunched}
              />
            ))}
            {/* Scroll anchor */}
            <div ref={scrollRef} />
          </div>
        )}
      </ScrollArea>

      {/* Input area */}
      <div className="border-t p-4">
        <ChatInput
          onSend={sendMessage}
          isLoading={isSending}
          disabled={!isConnected}
          placeholder="Ask about this insight..."
          maxLength={2000}
        />
      </div>
    </div>
  );
}
