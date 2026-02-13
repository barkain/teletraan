'use client';

import { useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useRouter } from 'next/navigation';
import {
  Sparkles,
  ArrowRight,
  Play,
  Loader2,
  TrendingUp,
  TrendingDown,
  Target,
  Clock,
  MessageSquare,
  BarChart3,
  AlertCircle,
  CheckCircle2,
  Minus,
  XCircle,
  Timer,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DeepInsightCard } from '@/components/insights/deep-insight-card';
import { AnalysisSummaryBanner } from '@/components/insights/analysis-summary-banner';
import { GradientProgressBar } from '@/components/insights/gradient-progress-bar';
import { useRecentDeepInsights } from '@/lib/hooks/use-deep-insights';
import { useAnalysisTask } from '@/lib/hooks/use-analysis-task';
import type { InsightAction, AutonomousAnalysisResponse } from '@/types';

// ============================================
// Types
// ============================================

interface AnalysisStats {
  totalInsights: number;
  buySignals: number;
  sellSignals: number;
  holdSignals: number;
  watchSignals: number;
}

// ============================================
// Skeleton Components
// ============================================

function InsightGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i}>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <Skeleton className="h-6 w-20 mb-2" />
                <Skeleton className="h-5 w-3/4" />
                <div className="flex gap-1 mt-2">
                  <Skeleton className="h-5 w-12" />
                  <Skeleton className="h-5 w-12" />
                </div>
              </div>
              <div className="text-right">
                <Skeleton className="h-8 w-12" />
                <Skeleton className="h-3 w-16 mt-1" />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3 mt-1" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function StatsSkeleton() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="pt-4">
            <Skeleton className="h-4 w-24 mb-2" />
            <Skeleton className="h-8 w-12" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ============================================
// Helper Functions
// ============================================

function formatRelativeTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatElapsedTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function computeStats(insights: { action: InsightAction }[]): AnalysisStats {
  const buyActions: InsightAction[] = ['STRONG_BUY', 'BUY'];
  const sellActions: InsightAction[] = ['STRONG_SELL', 'SELL'];
  const holdActions: InsightAction[] = ['HOLD'];
  const watchActions: InsightAction[] = ['WATCH'];

  return {
    totalInsights: insights.length,
    buySignals: insights.filter(i => buyActions.includes(i.action)).length,
    sellSignals: insights.filter(i => sellActions.includes(i.action)).length,
    holdSignals: insights.filter(i => holdActions.includes(i.action)).length,
    watchSignals: insights.filter(i => watchActions.includes(i.action)).length,
  };
}

// ============================================
// Stats Cards Component
// ============================================

function AnalysisStatsCards({ stats, isLoading }: { stats?: AnalysisStats; isLoading: boolean }) {
  if (isLoading) return <StatsSkeleton />;

  const statItems = [
    {
      label: 'Total Insights',
      value: stats?.totalInsights ?? 0,
      icon: Sparkles,
      color: 'text-primary',
    },
    {
      label: 'Buy Signals',
      value: stats?.buySignals ?? 0,
      icon: TrendingUp,
      color: 'text-green-500',
    },
    {
      label: 'Sell Signals',
      value: stats?.sellSignals ?? 0,
      icon: TrendingDown,
      color: 'text-red-500',
    },
    {
      label: 'Hold',
      value: stats?.holdSignals ?? 0,
      icon: Minus,
      color: 'text-yellow-500',
    },
    {
      label: 'Watch List',
      value: stats?.watchSignals ?? 0,
      icon: Target,
      color: 'text-blue-500',
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      {statItems.map((item) => {
        const Icon = item.icon;
        return (
          <Card key={item.label}>
            <CardContent className="pt-4">
              <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                <Icon className={`h-4 w-4 ${item.color}`} />
                {item.label}
              </div>
              <div className="text-2xl font-bold">{item.value}</div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

// ============================================
// Quick Filter Tabs
// ============================================

type FilterTab = 'all' | 'buy' | 'sell' | 'hold' | 'watch';

const filterTabConfig: Record<FilterTab, { label: string; actions: InsightAction[] | null }> = {
  all: { label: 'All Insights', actions: null },
  buy: { label: 'Buy Signals', actions: ['STRONG_BUY', 'BUY'] },
  sell: { label: 'Sell Signals', actions: ['STRONG_SELL', 'SELL'] },
  hold: { label: 'Hold', actions: ['HOLD'] },
  watch: { label: 'Watch', actions: ['WATCH'] },
};

// ============================================
// Empty State
// ============================================

function EmptyInsightsState({ onRunAnalysis, isRunning }: { onRunAnalysis: () => void; isRunning: boolean }) {
  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Sparkles className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No AI Insights Yet</CardTitle>
        <CardDescription className="max-w-md mb-6">
          Let our AI autonomously scan the market, analyze macro conditions, and discover trading opportunities across all sectors.
        </CardDescription>
        <Button onClick={onRunAnalysis} disabled={isRunning} size="lg">
          {isRunning ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Discovering Opportunities...
            </>
          ) : (
            <>
              <Play className="h-4 w-4" />
              Discover Opportunities
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}

// ============================================
// Analysis Status Banner with Progress Bar
// ============================================

interface AnalysisStatusBannerProps {
  isRunning: boolean;
  progress: number;
  phaseName?: string | null;
  phaseDetails?: string | null;
  error?: string | null;
  isComplete?: boolean;
  isCancelled?: boolean;
  elapsedSeconds?: number;
  onCancel?: () => void;
  task?: {
    market_regime?: string | null;
    top_sectors?: string[] | null;
    discovery_summary?: string | null;
    elapsed_seconds?: number | null;
    result_insight_ids?: number[] | null;
  } | null;
}

function AnalysisStatusBanner({
  isRunning,
  progress,
  phaseName,
  phaseDetails,
  error,
  isComplete,
  isCancelled,
  elapsedSeconds = 0,
  onCancel,
  task,
}: AnalysisStatusBannerProps) {
  if (error) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 bg-destructive/10 border border-destructive/20 rounded-lg">
        <AlertCircle className="h-5 w-5 text-destructive" />
        <div>
          <p className="font-medium text-sm text-destructive">Analysis Failed</p>
          <p className="text-xs text-muted-foreground">{error}</p>
        </div>
      </div>
    );
  }

  if (isCancelled) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 bg-muted/50 border border-muted-foreground/20 rounded-lg">
        <XCircle className="h-5 w-5 text-muted-foreground" />
        <div>
          <p className="font-medium text-sm text-muted-foreground">Analysis Cancelled</p>
          <p className="text-xs text-muted-foreground">The analysis was stopped by user request</p>
        </div>
      </div>
    );
  }

  if (isRunning) {
    return (
      <div className="px-4 py-4 bg-primary/5 border border-primary/20 rounded-lg">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <p className="font-medium text-sm">Autonomous Analysis in Progress</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Timer className="h-4 w-4" />
              <span className="font-mono">{formatElapsedTime(elapsedSeconds)}</span>
            </div>
            {onCancel && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onCancel}
                className="h-7 px-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              >
                <XCircle className="h-4 w-4 mr-1" />
                Cancel
              </Button>
            )}
            <span className="text-xs text-muted-foreground hidden sm:inline">
              {Math.round(progress)}%
            </span>
          </div>
        </div>
        <GradientProgressBar
          progress={progress}
          phaseName={phaseName || undefined}
          phaseDetails={phaseDetails || undefined}
        />
      </div>
    );
  }

  if (isComplete && task) {
    // Build a response-like object for the summary banner
    const analysisResult: AutonomousAnalysisResponse = {
      analysis_id: '',
      status: 'complete',
      insights_count: task.result_insight_ids?.length || 0,
      elapsed_seconds: task.elapsed_seconds || 0,
      discovery_summary: task.discovery_summary || '',
      market_regime: task.market_regime || '',
      top_sectors: task.top_sectors || [],
    };
    return <AnalysisSummaryBanner result={analysisResult} />;
  }

  if (isComplete) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 bg-green-500/10 border border-green-500/20 rounded-lg">
        <CheckCircle2 className="h-5 w-5 text-green-500" />
        <div>
          <p className="font-medium text-sm text-green-600 dark:text-green-400">Analysis Complete</p>
          <p className="text-xs text-muted-foreground">New insights are now available</p>
        </div>
      </div>
    );
  }

  return null;
}

// ============================================
// Recent Conversations (Placeholder)
// ============================================

function RecentConversationsSection() {
  // In a real implementation, this would fetch recent conversations
  // For now, we'll show a placeholder that encourages users to explore insights

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-lg">Continue Your Research</CardTitle>
          </div>
          <Link
            href="/insights"
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            View All
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
        <CardDescription>
          Click on any insight card to discuss it with our AI assistant
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-center py-6 text-center text-muted-foreground">
          <div className="space-y-2">
            <MessageSquare className="h-8 w-8 mx-auto opacity-50" />
            <p className="text-sm">No recent conversations</p>
            <p className="text-xs">Start by clicking on an insight to discuss it</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ============================================
// Market Status Badge
// ============================================

function MarketStatusBadge() {
  const now = new Date();
  const hour = now.getUTCHours();
  const day = now.getUTCDay();

  // Simple market hours check (NYSE: 9:30 AM - 4:00 PM ET, Mon-Fri)
  // ET is UTC-5 (or UTC-4 during DST)
  const isWeekday = day >= 1 && day <= 5;
  const marketOpenHour = 14; // 9:30 AM ET in UTC (approximate)
  const marketCloseHour = 21; // 4:00 PM ET in UTC
  const isMarketHours = hour >= marketOpenHour && hour < marketCloseHour;
  const isOpen = isWeekday && isMarketHours;

  return (
    <Badge variant={isOpen ? 'default' : 'secondary'} className="gap-1">
      <span className={`h-2 w-2 rounded-full ${isOpen ? 'bg-green-400 animate-pulse' : 'bg-muted-foreground'}`} />
      Market {isOpen ? 'Open' : 'Closed'}
    </Badge>
  );
}

// ============================================
// Main Page Component
// ============================================

export default function InsightHubPage() {
  const router = useRouter();
  const [activeFilter, setActiveFilter] = useState<FilterTab>('all');

  // Fetch insights - only fetch what we display (9 max) for fast initial load
  const { data: allInsightsData, isLoading: isLoadingAll, isFetching } = useRecentDeepInsights(9);

  // Use background analysis task hook
  const {
    task,
    isRunning: isAnalysisRunning,
    isComplete: isAnalysisComplete,
    isFailed: isAnalysisFailed,
    isCancelled: isAnalysisCancelled,
    error: analysisError,
    elapsedSeconds,
    startAnalysis,
    cancelAnalysis,
  } = useAnalysisTask({
    pollInterval: 2000,
  });

  // Get filter configuration for current tab
  const filterConfig = filterTabConfig[activeFilter];

  // Compute stats from all insights
  const stats = allInsightsData?.items ? computeStats(allInsightsData.items) : undefined;

  // Get last analysis time from most recent insight
  const lastAnalysisTime = allInsightsData?.items?.[0]?.created_at;

  // Get insights to display (filtered or all based on active tab)
  // Filter client-side to properly handle multi-action filters (e.g., 'sell' includes both SELL and STRONG_SELL)
  const displayInsights = activeFilter === 'all'
    ? allInsightsData?.items?.slice(0, 9)
    : allInsightsData?.items?.filter(i => filterConfig.actions?.includes(i.action)).slice(0, 9);

  // Only show full skeleton on initial load (no cached data)
  // If we have stale data, show it immediately while refreshing in background
  const hasData = allInsightsData?.items && allInsightsData.items.length > 0;
  const isLoading = isLoadingAll && !hasData;

  const handleSymbolClick = (symbol: string) => {
    router.push(`/stocks/${symbol}`);
  };

  const handleInsightClick = (insightId: number) => {
    router.push(`/insights/${insightId}`);
  };

  const handleRunAnalysis = () => {
    startAnalysis({ max_insights: 5, deep_dive_count: 7 });
  };

  return (
    <div className="space-y-6">
      {/* Hero Banner */}
      <div className="relative w-full max-h-96 rounded-xl overflow-hidden">
        <Image
          src="/teletraan-hero.png"
          alt="Teletraan Command Center — AI-powered market intelligence"
          className="w-full h-64 md:h-96 object-cover"
          width={1200}
          height={400}
          priority
        />
        {/* Gradient overlay for smooth transition to content below */}
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/40 to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-b from-background/20 to-transparent" />
      </div>

      {/* Hero Section */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 -mt-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">Teletraan</h1>
            <MarketStatusBadge />
          </div>
          <p className="text-muted-foreground">
            AI-Powered Market Intelligence -- multi-agent deep analysis
          </p>
          {lastAnalysisTime && (
            <p className="text-sm text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Last analysis: {formatRelativeTime(lastAnalysisTime)}
            </p>
          )}
        </div>
        <Button
          onClick={handleRunAnalysis}
          disabled={isAnalysisRunning}
          size="lg"
          className="md:w-auto w-full"
        >
          {isAnalysisRunning ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Discovering...
            </>
          ) : (
            <>
              <Play className="h-4 w-4" />
              Discover Opportunities
            </>
          )}
        </Button>
      </div>

      {/* Analysis Status Banner with Progress */}
      {(isAnalysisRunning || isAnalysisComplete || isAnalysisFailed || isAnalysisCancelled || analysisError) && (
        <AnalysisStatusBanner
          isRunning={isAnalysisRunning}
          progress={task?.progress || 0}
          phaseName={task?.phase_name}
          phaseDetails={task?.phase_details}
          error={analysisError}
          isComplete={isAnalysisComplete}
          isCancelled={isAnalysisCancelled}
          elapsedSeconds={elapsedSeconds}
          onCancel={cancelAnalysis}
          task={task}
        />
      )}

      {/* Quick Stats - only show skeleton if no cached data */}
      <AnalysisStatsCards stats={stats} isLoading={isLoading} />

      {/* Main Insights Section */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-primary" />
            <h2 className="text-xl font-semibold">Latest Insights</h2>
            {/* Show subtle refresh indicator when fetching fresh data in background */}
            {isFetching && hasData && (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            )}
          </div>
          <Link
            href="/insights"
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            View All
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>

        {/* Quick Filter Tabs */}
        <Tabs value={activeFilter} onValueChange={(v) => setActiveFilter(v as FilterTab)} className="mb-4">
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="buy" className="text-green-600 dark:text-green-400">
              <TrendingUp className="h-4 w-4 mr-1" />
              Buy
            </TabsTrigger>
            <TabsTrigger value="sell" className="text-red-600 dark:text-red-400">
              <TrendingDown className="h-4 w-4 mr-1" />
              Sell
            </TabsTrigger>
            <TabsTrigger value="hold" className="text-yellow-600 dark:text-yellow-400">
              <Minus className="h-4 w-4 mr-1" />
              Hold
            </TabsTrigger>
            <TabsTrigger value="watch" className="text-blue-600 dark:text-blue-400">
              <Target className="h-4 w-4 mr-1" />
              Watch
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {/* Insights Grid */}
        {isLoading ? (
          <InsightGridSkeleton count={6} />
        ) : !displayInsights || displayInsights.length === 0 ? (
          <EmptyInsightsState
            onRunAnalysis={handleRunAnalysis}
            isRunning={isAnalysisRunning}
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {displayInsights.map((insight) => (
              <DeepInsightCard
                key={insight.id}
                insight={insight}
                onSymbolClick={handleSymbolClick}
                onClick={() => handleInsightClick(insight.id)}
              />
            ))}
          </div>
        )}

        {/* Show "View More" if there are more insights */}
        {displayInsights && displayInsights.length >= 9 && (
          <div className="flex justify-center mt-6">
            <Link href="/insights">
              <Button variant="outline">
                View All Insights
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        )}
      </section>

      {/* Recent Conversations Section */}
      <RecentConversationsSection />
    </div>
  );
}
