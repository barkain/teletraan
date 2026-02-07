'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNow } from 'date-fns';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  Clock,
  Target,
  Shield,
  History,
  Users,
  CalendarClock,
  RefreshCw,
  Plus,
  MessageSquare,
  ChevronRight,
  ArrowLeft,
  Loader2,
  Database,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { TooltipProvider } from '@/components/ui/tooltip';
import { InsightConversationPanel } from '@/components/insights/insight-conversation-panel';
import { StatisticalSignalsCard } from '@/components/insights/statistical-signals-card';
import { OutcomeBadge } from '@/components/insights/outcome-badge';
import { DiscoveryContextCard } from '@/components/insights/discovery-context-card';
import { useDeepInsight, deepInsightKeys } from '@/lib/hooks/use-deep-insights';
import {
  useInsightConversations,
  type InsightConversation,
} from '@/lib/hooks/use-insight-conversation';
import type { DeepInsight, InsightAction } from '@/types';

// ============================================
// Types
// ============================================

interface InsightDetailViewProps {
  insightId: number;
}

// ============================================
// Action Config (matching deep-insight-card.tsx)
// ============================================

const actionConfig: Record<InsightAction, { color: string; icon: typeof TrendingUp; label: string; bgColor: string }> = {
  STRONG_BUY: { color: 'bg-green-600', icon: TrendingUp, label: 'Strong Buy', bgColor: 'bg-green-600/10' },
  BUY: { color: 'bg-green-500', icon: TrendingUp, label: 'Buy', bgColor: 'bg-green-500/10' },
  HOLD: { color: 'bg-yellow-500', icon: Minus, label: 'Hold', bgColor: 'bg-yellow-500/10' },
  SELL: { color: 'bg-red-500', icon: TrendingDown, label: 'Sell', bgColor: 'bg-red-500/10' },
  STRONG_SELL: { color: 'bg-red-600', icon: TrendingDown, label: 'Strong Sell', bgColor: 'bg-red-600/10' },
  WATCH: { color: 'bg-blue-500', icon: Target, label: 'Watch', bgColor: 'bg-blue-500/10' },
};

// ============================================
// Helper Functions
// ============================================

/**
 * Format a timestamp into a full, explicit date/time string
 * Output format: "Feb 1, 2026, 3:30 PM EST"
 */
function formatInsightDate(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  });
}

// ============================================
// Sub-Components
// ============================================

function ConfidenceIndicator({ confidence }: { confidence: number }) {
  const percentage = Math.round(confidence * 100);
  const getColor = () => {
    if (percentage >= 80) return 'text-green-600 bg-green-100 dark:bg-green-900/30';
    if (percentage >= 60) return 'text-yellow-600 bg-yellow-100 dark:bg-yellow-900/30';
    return 'text-red-600 bg-red-100 dark:bg-red-900/30';
  };

  return (
    <div className={cn('rounded-lg px-4 py-3 text-center', getColor())}>
      <div className="text-3xl font-bold">{percentage}%</div>
      <div className="text-xs font-medium uppercase tracking-wide opacity-80">Confidence</div>
    </div>
  );
}

function ConversationListItem({
  conversation,
  isActive,
  onClick,
}: {
  conversation: InsightConversation;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors',
        isActive
          ? 'bg-primary/10 text-primary'
          : 'hover:bg-muted/50 text-muted-foreground hover:text-foreground'
      )}
    >
      <MessageSquare className="h-4 w-4 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{conversation.title}</p>
        <p className="text-xs text-muted-foreground">
          {formatDistanceToNow(new Date(conversation.updated_at), { addSuffix: true })}
        </p>
      </div>
      {isActive && <ChevronRight className="h-4 w-4 flex-shrink-0" />}
    </button>
  );
}

function InsightDetailsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-start gap-6">
        <Skeleton className="h-16 w-32" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
        <Skeleton className="h-16 w-24" />
      </div>
      <Skeleton className="h-px w-full" />
      <div className="space-y-4">
        <Skeleton className="h-4 w-32" />
        <div className="flex gap-2">
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-6 w-16" />
        </div>
      </div>
      <Skeleton className="h-px w-full" />
      <div className="space-y-4">
        <Skeleton className="h-4 w-40" />
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      </div>
    </div>
  );
}

// ============================================
// Insight Details Panel
// ============================================

function InsightDetailsPanel({
  insight,
  onRefresh,
  isRefreshing,
  onSymbolClick,
}: {
  insight: DeepInsight;
  onRefresh: () => void;
  isRefreshing: boolean;
  onSymbolClick: (symbol: string) => void;
}) {
  const actionInfo = actionConfig[insight.action];
  const ActionIcon = actionInfo.icon;

  return (
    <div className="space-y-6">
      {/* Header Section */}
      <div className="flex flex-col lg:flex-row lg:items-start gap-4 lg:gap-6">
        {/* Action Badge - Large and Prominent */}
        <div className={cn('p-4 rounded-xl flex flex-col items-center justify-center min-w-[120px]', actionInfo.bgColor)}>
          <Badge className={cn('text-white text-sm px-4 py-2', actionInfo.color)}>
            <ActionIcon className="w-4 h-4 mr-2" />
            {actionInfo.label}
          </Badge>
        </div>

        {/* Title and Thesis */}
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold tracking-tight mb-2">{insight.title}</h1>
          <p className="text-muted-foreground leading-relaxed">{insight.thesis}</p>
        </div>

        {/* Confidence Score */}
        <ConfidenceIndicator confidence={insight.confidence} />

        {/* Outcome Badge for actionable insights */}
        {(insight.action === 'BUY' || insight.action === 'STRONG_BUY' ||
          insight.action === 'SELL' || insight.action === 'STRONG_SELL') && (
          <TooltipProvider>
            <OutcomeBadge
              insightId={insight.id}
              size="lg"
              showDetails={true}
            />
          </TooltipProvider>
        )}
      </div>

      <Separator />

      {/* Time and Symbols Section */}
      <div className="flex flex-wrap gap-6">
        {/* Time Horizon */}
        <div className="flex items-center gap-2">
          <Clock className="h-5 w-5 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">{insight.time_horizon}</p>
            <p className="text-xs text-muted-foreground">Time Horizon</p>
          </div>
        </div>

        {/* Insight Type */}
        <div>
          <Badge variant="outline" className="capitalize">
            {insight.insight_type}
          </Badge>
          <p className="text-xs text-muted-foreground mt-1">Insight Type</p>
        </div>

        {/* Timestamps - Explicit Date/Time Display */}
        <div className="flex items-center gap-2">
          <CalendarClock className="h-5 w-5 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">
              {formatInsightDate(insight.created_at)}
            </p>
            <p className="text-xs text-muted-foreground">Analysis Date</p>
          </div>
        </div>

        {insight.updated_at && insight.updated_at !== insight.created_at && (
          <div className="flex items-center gap-2">
            <RefreshCw className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">
                {formatInsightDate(insight.updated_at)}
              </p>
              <p className="text-xs text-muted-foreground">Last Updated</p>
            </div>
          </div>
        )}
      </div>

      <Separator />

      {/* Symbols Section */}
      <div>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Target className="h-4 w-4" /> Symbols
        </h3>
        <div className="flex flex-wrap gap-2">
          {insight.primary_symbol && (
            <Badge
              variant="default"
              className="cursor-pointer hover:opacity-80 transition-opacity"
              onClick={() => onSymbolClick(insight.primary_symbol!)}
            >
              {insight.primary_symbol}
              <span className="ml-1 text-xs opacity-70">Primary</span>
            </Badge>
          )}
          {insight.related_symbols.map((symbol) => (
            <Badge
              key={symbol}
              variant="secondary"
              className="cursor-pointer hover:bg-secondary/80 transition-colors"
              onClick={() => onSymbolClick(symbol)}
            >
              {symbol}
            </Badge>
          ))}
          {!insight.primary_symbol && insight.related_symbols.length === 0 && (
            <p className="text-sm text-muted-foreground">No specific symbols</p>
          )}
        </div>
      </div>

      {/* Statistical Signals for Primary Symbol */}
      {insight.primary_symbol && (
        <>
          <Separator />
          <StatisticalSignalsCard
            symbol={insight.primary_symbol}
            maxSignals={5}
            className="border-0 shadow-none p-0"
          />
        </>
      )}

      <Separator />

      {/* Supporting Evidence */}
      <div>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Users className="h-4 w-4" /> Supporting Evidence from Analysts
        </h3>
        <div className="space-y-3">
          {insight.supporting_evidence.map((evidence, i) => (
            <Card key={i} className="bg-muted/30">
              <CardContent className="pt-4">
                <div className="flex items-start gap-3">
                  <Badge variant="outline" className="capitalize shrink-0">
                    {evidence.analyst}
                  </Badge>
                  <p className="text-sm text-muted-foreground flex-1">{evidence.finding}</p>
                  {evidence.confidence && (
                    <span className="text-xs text-muted-foreground shrink-0">
                      {Math.round(evidence.confidence * 100)}%
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
          {insight.supporting_evidence.length === 0 && (
            <p className="text-sm text-muted-foreground">No supporting evidence available</p>
          )}
        </div>
      </div>

      <Separator />

      {/* Risk Factors */}
      {insight.risk_factors.length > 0 && (
        <>
          <div>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-yellow-500" /> Risk Factors
            </h3>
            <ul className="space-y-2">
              {insight.risk_factors.map((risk, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="text-yellow-500 mt-1">-</span>
                  <span className="text-muted-foreground">{risk}</span>
                </li>
              ))}
            </ul>
          </div>
          <Separator />
        </>
      )}

      {/* Invalidation Trigger */}
      {insight.invalidation_trigger && (
        <>
          <div>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <Shield className="h-4 w-4 text-red-500" /> Invalidation Trigger
            </h3>
            <Card className="border-red-500/20 bg-red-500/5">
              <CardContent className="pt-4">
                <p className="text-sm text-muted-foreground">{insight.invalidation_trigger}</p>
              </CardContent>
            </Card>
          </div>
          <Separator />
        </>
      )}

      {/* Historical Precedent */}
      {insight.historical_precedent && (
        <>
          <div>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <History className="h-4 w-4" /> Historical Precedent
            </h3>
            <Card className="bg-muted/30">
              <CardContent className="pt-4">
                <p className="text-sm text-muted-foreground">{insight.historical_precedent}</p>
              </CardContent>
            </Card>
          </div>
          <Separator />
        </>
      )}

      {/* Metadata */}
      <div className="flex flex-wrap gap-6 text-sm text-muted-foreground">
        {insight.analysts_involved.length > 0 && (
          <div>
            <span className="font-medium">Analysts:</span>{' '}
            {insight.analysts_involved.join(', ')}
          </div>
        )}
        {insight.data_sources.length > 0 && (
          <div className="flex items-center gap-1">
            <Database className="h-3 w-3" />
            <span className="font-medium">Sources:</span>{' '}
            {insight.data_sources.join(', ')}
          </div>
        )}
      </div>

      {/* Discovery Context - shows how this insight was discovered */}
      {insight.discovery_context && (
        <>
          <Separator />
          <DiscoveryContextCard
            context={insight.discovery_context}
            className="border-0 shadow-none p-0"
          />
        </>
      )}

      {/* Refresh Button */}
      <div className="pt-4">
        <Button variant="outline" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={cn('h-4 w-4 mr-2', isRefreshing && 'animate-spin')} />
          {isRefreshing ? 'Refreshing...' : 'Refresh Data'}
        </Button>
      </div>
    </div>
  );
}

// ============================================
// Conversations Panel
// ============================================

function ConversationsPanel({
  insightId,
  selectedConversationId,
  onSelectConversation,
  onCreateConversation,
  isCreating,
  onModificationApplied,
  onResearchLaunched,
}: {
  insightId: number;
  selectedConversationId: number | null;
  onSelectConversation: (id: number | null) => void;
  onCreateConversation: () => void;
  isCreating: boolean;
  onModificationApplied?: () => void;
  onResearchLaunched?: (researchId: number) => void;
}) {
  const { conversations, isLoading } = useInsightConversations(insightId);

  return (
    <div className="flex flex-col h-full">
      {/* Conversations Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <h3 className="font-medium">Conversations</h3>
        <Button
          size="sm"
          onClick={onCreateConversation}
          disabled={isCreating}
        >
          {isCreating ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <Plus className="h-4 w-4 mr-1" />
          )}
          New
        </Button>
      </div>

      <Tabs
        value={selectedConversationId ? 'chat' : 'list'}
        onValueChange={(v) => {
          if (v === 'list') onSelectConversation(null);
        }}
        className="flex-1 flex flex-col"
      >
        <TabsList className="mx-4 mt-2" variant="line">
          <TabsTrigger value="list">
            <MessageSquare className="h-4 w-4 mr-1" />
            All ({conversations.length})
          </TabsTrigger>
          <TabsTrigger value="chat" disabled={!selectedConversationId}>
            Active Chat
          </TabsTrigger>
        </TabsList>

        {/* Conversations List */}
        <TabsContent value="list" className="flex-1 m-0">
          <ScrollArea className="h-full">
            <div className="p-4 space-y-2">
              {isLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <MessageSquare className="h-12 w-12 text-muted-foreground mb-4" />
                  <h4 className="text-lg font-medium mb-2">No Conversations Yet</h4>
                  <p className="text-sm text-muted-foreground max-w-xs mb-4">
                    Start a conversation to ask questions about this insight or request modifications.
                  </p>
                  <Button onClick={onCreateConversation} disabled={isCreating}>
                    {isCreating ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Plus className="h-4 w-4 mr-2" />
                    )}
                    Start Conversation
                  </Button>
                </div>
              ) : (
                conversations.map((conv) => (
                  <ConversationListItem
                    key={conv.id}
                    conversation={conv}
                    isActive={conv.id === selectedConversationId}
                    onClick={() => onSelectConversation(conv.id)}
                  />
                ))
              )}
            </div>
          </ScrollArea>
        </TabsContent>

        {/* Active Conversation */}
        <TabsContent value="chat" className="flex-1 min-h-0 overflow-hidden m-0">
          {selectedConversationId && (
            <InsightConversationPanel
              conversationId={selectedConversationId}
              insightId={insightId}
              onModificationApplied={onModificationApplied}
              onResearchLaunched={onResearchLaunched}
            />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ============================================
// Main Component
// ============================================

export function InsightDetailView({ insightId }: InsightDetailViewProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  // State
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);

  // Fetch insight data
  const { data: insight, isLoading, error, refetch, isFetching } = useDeepInsight(insightId);

  // Conversations
  const { createConversationAsync, isCreating } = useInsightConversations(insightId);

  // Handlers
  const handleRefresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  const handleSymbolClick = useCallback((symbol: string) => {
    router.push(`/stocks/${symbol}`);
  }, [router]);

  const handleCreateConversation = useCallback(async () => {
    try {
      const newConversation = await createConversationAsync({
        title: `Conversation ${new Date().toLocaleDateString()}`,
      });
      setSelectedConversationId(newConversation.id);
    } catch (err) {
      console.error('Failed to create conversation:', err);
    }
  }, [createConversationAsync]);

  const handleModificationApplied = useCallback(() => {
    // Refresh insight data when a modification is applied
    queryClient.invalidateQueries({ queryKey: deepInsightKeys.detail(insightId) });
  }, [queryClient, insightId]);

  const handleResearchLaunched = useCallback((researchId: number) => {
    console.log('Research launched:', researchId);
    // Could navigate to research page or show notification
  }, []);

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10" />
          <Skeleton className="h-8 w-64" />
        </div>
        <div className="grid lg:grid-cols-[1fr,400px] gap-6">
          <Card>
            <CardContent className="pt-6">
              <InsightDetailsSkeleton />
            </CardContent>
          </Card>
          <Card className="h-[600px]">
            <CardContent className="pt-6">
              <Skeleton className="h-full w-full" />
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // Error state
  if (error || !insight) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" onClick={() => router.push('/insights')}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Insights
        </Button>
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <AlertTriangle className="h-12 w-12 text-destructive mb-4" />
            <CardTitle className="text-lg mb-2">Error Loading Insight</CardTitle>
            <CardDescription className="max-w-sm mb-4">
              {error instanceof Error ? error.message : 'Failed to load insight details'}
            </CardDescription>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => router.push('/insights')}>
                Back to Insights
              </Button>
              <Button onClick={() => refetch()}>
                Try Again
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Back Navigation */}
      <Button variant="ghost" onClick={() => router.push('/insights')}>
        <ArrowLeft className="h-4 w-4 mr-2" />
        Back to Insights
      </Button>

      {/* Two-Column Layout */}
      <div className="grid lg:grid-cols-[1fr,400px] gap-6">
        {/* Left Column: Insight Details */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Target className="h-5 w-5" />
              Insight Details
            </CardTitle>
            <CardDescription>
              Deep analysis synthesized from multiple AI analysts
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[calc(100vh-280px)] pr-4">
              <InsightDetailsPanel
                insight={insight}
                onRefresh={handleRefresh}
                isRefreshing={isFetching}
                onSymbolClick={handleSymbolClick}
              />
            </ScrollArea>
          </CardContent>
        </Card>

        {/* Right Column: Conversations */}
        <Card className="h-[calc(100vh-200px)] flex flex-col">
          <ConversationsPanel
            insightId={insightId}
            selectedConversationId={selectedConversationId}
            onSelectConversation={setSelectedConversationId}
            onCreateConversation={handleCreateConversation}
            isCreating={isCreating}
            onModificationApplied={handleModificationApplied}
            onResearchLaunched={handleResearchLaunched}
          />
        </Card>
      </div>
    </div>
  );
}
