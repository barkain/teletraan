'use client';

import { useMemo, useState, useEffect } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  Sparkles,
  ArrowRight,
  Play,
  Loader2,
  TrendingUp,
  TrendingDown,
  Target,
  Clock,
  AlertCircle,
  CheckCircle2,
  Minus,
  XCircle,
  Timer,
  Activity,
  Eye,
  BarChart3,
  PieChart as PieChartIcon,
  Hash,
  Layers,
} from 'lucide-react';
import {
  ComposedChart,
  Area,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Legend,
} from 'recharts';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { AnalysisSummaryBanner } from '@/components/insights/analysis-summary-banner';
import { GradientProgressBar } from '@/components/insights/gradient-progress-bar';
import { useRecentDeepInsights } from '@/lib/hooks/use-deep-insights';
import { useAnalysisTask } from '@/lib/hooks/use-analysis-task';
import { knowledgeApi, outcomesApi } from '@/lib/api';
import type { DeepInsight, InsightAction, AutonomousAnalysisResponse } from '@/types';
import type { TrackRecordStats, MonthlyTrendResponse, OutcomeSummary } from '@/lib/types/track-record';
import type { PatternsSummary } from '@/lib/types/knowledge';

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

interface ConfidenceBucket {
  range: string;
  count: number;
  fill: string;
}

// ============================================
// Constants
// ============================================

const ACTION_COLORS: Record<string, string> = {
  BUY: '#22c55e',
  STRONG_BUY: '#16a34a',
  SELL: '#ef4444',
  STRONG_SELL: '#dc2626',
  HOLD: '#f59e0b',
  WATCH: '#3b82f6',
};

const TYPE_COLORS: Record<string, string> = {
  opportunity: '#22c55e',
  risk: '#ef4444',
  rotation: '#8b5cf6',
  macro: '#3b82f6',
  earnings: '#f59e0b',
  technical: '#06b6d4',
  sentiment: '#ec4899',
  thematic: '#a855f7',
};

const CONFIDENCE_COLORS = [
  '#ef4444', // 0-20 red
  '#f97316', // 20-40 orange
  '#f59e0b', // 40-60 amber
  '#84cc16', // 60-80 lime
  '#22c55e', // 80-100 green
];

// ============================================
// Skeleton Components
// ============================================

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

function ChartSkeleton({ height = 300 }: { height?: number }) {
  return (
    <div className="flex items-center justify-center" style={{ height }}>
      <div className="space-y-3 w-full px-6">
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-[200px] w-full rounded-lg" />
        <div className="flex justify-between">
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-12" />
        </div>
      </div>
    </div>
  );
}

// ============================================
// Helper Functions
// ============================================

function formatRelativeTime(timestamp: string): string {
  // Backend returns naive UTC datetimes (e.g. "2026-02-14T10:30:00") without
  // a timezone suffix. Append 'Z' so the browser parses them as UTC rather
  // than local time, which would make the "ago" text appear hours off.
  const normalized = timestamp.endsWith('Z') || timestamp.includes('+') || timestamp.includes('-', 10)
    ? timestamp
    : timestamp + 'Z';
  const date = new Date(normalized);
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

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'N/A';
  return `${(value * 100).toFixed(1)}%`;
}

function formatReturn(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'N/A';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${(value * 100).toFixed(1)}%`;
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
          <Card key={item.label} className="bg-card/80 backdrop-blur-sm border-border/50">
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
// Market Status Badge
// ============================================

function MarketStatusBadge() {
  const now = new Date();
  const hour = now.getUTCHours();
  const day = now.getUTCDay();

  const isWeekday = day >= 1 && day <= 5;
  const marketOpenHour = 14;
  const marketCloseHour = 21;
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
// Custom Tooltip for Charts
// ============================================

const tooltipStyle = {
  background: 'rgba(15, 15, 15, 0.92)',
  backdropFilter: 'blur(12px)',
  border: '1px solid rgba(255, 255, 255, 0.08)',
  borderRadius: '12px',
  padding: '10px 16px',
  boxShadow: '0 8px 24px rgba(0, 0, 0, 0.5)',
} as const;

const tooltipWrapperStyle = {
  background: 'transparent',
  border: 'none',
  boxShadow: 'none',
  outline: 'none',
  borderRadius: '12px',
} as const;

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="text-sm" style={tooltipStyle}>
      <p className="font-medium text-white/90 mb-1">{label}</p>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-2 text-white/60">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span>{entry.name}:</span>
          <span className="font-medium text-white/90">
            {entry.name.toLowerCase().includes('rate') ? `${(entry.value * 100).toFixed(1)}%` : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// ============================================
// Monthly Trend Chart
// ============================================

function MonthlyTrendChart({ data, insights, isLoading }: { data?: MonthlyTrendResponse; insights?: DeepInsight[]; isLoading: boolean }) {
  const hasBackendData = data?.data && data.data.length > 0;

  const chartData = useMemo(() => {
    // Primary: use backend data if available
    if (hasBackendData) {
      return data!.data.map(d => ({
        month: d.month,
        rate: d.rate,
        total: d.total ?? 0,
        successful: d.successful ?? 0,
      }));
    }
    // Fallback: compute from insight creation dates
    if (insights && insights.length > 0) {
      const monthlyCounts: Record<string, number> = {};
      for (const insight of insights) {
        const date = new Date(insight.created_at);
        const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
        monthlyCounts[key] = (monthlyCounts[key] || 0) + 1;
      }
      return Object.entries(monthlyCounts)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([month, total]) => ({
          month,
          rate: 0,
          total,
          successful: 0,
        }));
    }
    return [];
  }, [data, hasBackendData, insights]);

  return (
    <Card className="bg-card/80 backdrop-blur-sm border-border/50">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Monthly Performance Trend</CardTitle>
        </div>
        <CardDescription>{hasBackendData ? 'Success rate and insight volume over time' : 'Insight volume over time'}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <ChartSkeleton />
        ) : chartData.length === 0 ? (
          <EmptyChartState message="No monthly trend data yet" />
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
              <defs>
                <linearGradient id="successGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#22c55e" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border/30" />
              <XAxis
                dataKey="month"
                tick={{ fontSize: 12 }}
                className="fill-muted-foreground"
                tickFormatter={(v: string) => {
                  const [, m] = v.split('-');
                  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                  return months[parseInt(m, 10) - 1] || v;
                }}
              />
              {hasBackendData && (
                <YAxis
                  yAxisId="rate"
                  orientation="left"
                  tick={{ fontSize: 12 }}
                  className="fill-muted-foreground"
                  tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                  domain={[0, 1]}
                />
              )}
              <YAxis
                yAxisId="count"
                orientation={hasBackendData ? 'right' : 'left'}
                tick={{ fontSize: 12 }}
                className="fill-muted-foreground"
                allowDecimals={false}
              />
              <Tooltip content={<ChartTooltip />} wrapperStyle={tooltipWrapperStyle} cursor={{ stroke: 'rgba(255, 255, 255, 0.15)', strokeWidth: 1 }} />
              <Legend
                wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              />
              <Bar
                yAxisId="count"
                dataKey="total"
                name="Total Insights"
                fill="#3b82f6"
                opacity={hasBackendData ? 0.3 : 0.7}
                radius={[4, 4, 0, 0]}
              />
              {hasBackendData && (
                <Area
                  yAxisId="rate"
                  type="monotone"
                  dataKey="rate"
                  name="Success Rate"
                  stroke="#22c55e"
                  strokeWidth={2.5}
                  fill="url(#successGradient)"
                  dot={{ fill: '#22c55e', r: 4, strokeWidth: 0 }}
                  activeDot={{ r: 6, fill: '#22c55e', stroke: '#fff', strokeWidth: 2 }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================
// Action Distribution Donut Chart
// ============================================

function ActionDistributionChart({ insights, trackRecord, isLoading }: { insights?: DeepInsight[]; trackRecord?: TrackRecordStats; isLoading: boolean }) {
  const chartData = useMemo(() => {
    // Primary source: compute from insights
    if (insights && insights.length > 0) {
      const counts: Record<string, number> = {};
      for (const insight of insights) {
        counts[insight.action] = (counts[insight.action] || 0) + 1;
      }
      return Object.entries(counts)
        .map(([action, count]) => ({
          name: action.replace('_', ' '),
          value: count,
          fill: ACTION_COLORS[action] || '#6b7280',
        }))
        .filter(d => d.value > 0);
    }
    // Fallback: use trackRecord if available
    if (trackRecord?.by_action) {
      return Object.entries(trackRecord.by_action)
        .map(([action, stats]) => ({
          name: action.replace('_', ' '),
          value: stats.total,
          fill: ACTION_COLORS[action] || '#6b7280',
        }))
        .filter(d => d.value > 0);
    }
    return [];
  }, [insights, trackRecord]);

  const totalCount = useMemo(() => chartData.reduce((s, d) => s + d.value, 0), [chartData]);

  return (
    <Card className="bg-card/80 backdrop-blur-sm border-border/50">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <PieChartIcon className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Action Distribution</CardTitle>
        </div>
        <CardDescription>Breakdown of insight recommendations</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <ChartSkeleton />
        ) : chartData.length === 0 ? (
          <EmptyChartState message="No action data yet" />
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={70}
                outerRadius={110}
                paddingAngle={3}
                dataKey="value"
                stroke="none"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip
                wrapperStyle={tooltipWrapperStyle}
                cursor={false}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload;
                  return (
                    <div className="text-sm" style={tooltipStyle}>
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: d.fill }} />
                        <span className="font-medium text-white/90">{d.name}</span>
                      </div>
                      <p className="text-white/60 mt-1">
                        {d.value} insights ({((d.value / totalCount) * 100).toFixed(1)}%)
                      </p>
                    </div>
                  );
                }}
              />
              {/* Center text */}
              <text
                x="50%"
                y="46%"
                textAnchor="middle"
                dominantBaseline="central"
                className="fill-foreground text-3xl font-bold"
                style={{ fontSize: 28, fontWeight: 700 }}
              >
                {totalCount}
              </text>
              <text
                x="50%"
                y="57%"
                textAnchor="middle"
                dominantBaseline="central"
                className="fill-muted-foreground"
                style={{ fontSize: 12 }}
              >
                total
              </text>
            </PieChart>
          </ResponsiveContainer>
        )}
        {/* Legend below chart */}
        {chartData.length > 0 && (
          <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 mt-2">
            {chartData.map((d) => (
              <div key={d.name} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: d.fill }} />
                {d.name}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================
// Confidence Distribution Histogram
// ============================================

function ConfidenceDistributionChart({ insights, isLoading }: { insights?: { confidence: number }[]; isLoading: boolean }) {
  const buckets: ConfidenceBucket[] = useMemo(() => {
    const ranges = ['0-20%', '20-40%', '40-60%', '60-80%', '80-100%'];
    const counts = [0, 0, 0, 0, 0];

    if (insights) {
      for (const item of insights) {
        const c = item.confidence * 100;
        if (c < 20) counts[0]++;
        else if (c < 40) counts[1]++;
        else if (c < 60) counts[2]++;
        else if (c < 80) counts[3]++;
        else counts[4]++;
      }
    }

    return ranges.map((range, i) => ({
      range,
      count: counts[i],
      fill: CONFIDENCE_COLORS[i],
    }));
  }, [insights]);

  const hasData = buckets.some(b => b.count > 0);

  return (
    <Card className="bg-card/80 backdrop-blur-sm border-border/50">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Confidence Distribution</CardTitle>
        </div>
        <CardDescription>How confident our insights are</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <ChartSkeleton />
        ) : !hasData ? (
          <EmptyChartState message="No confidence data yet" />
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={buckets} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border/30" />
              <XAxis
                dataKey="range"
                tick={{ fontSize: 12 }}
                className="fill-muted-foreground"
              />
              <YAxis
                tick={{ fontSize: 12 }}
                className="fill-muted-foreground"
                allowDecimals={false}
              />
              <Tooltip
                wrapperStyle={tooltipWrapperStyle}
                cursor={{ fill: 'rgba(255, 255, 255, 0.05)' }}
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null;
                  return (
                    <div className="text-sm" style={tooltipStyle}>
                      <p className="font-medium text-white/90">{label}</p>
                      <p className="text-white/60">{payload[0].value} insights</p>
                    </div>
                  );
                }}
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {buckets.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================
// Performance by Insight Type (Horizontal Bar)
// ============================================

function PerformanceByTypeChart({ insights, trackRecord, isLoading }: { insights?: DeepInsight[]; trackRecord?: TrackRecordStats; isLoading: boolean }) {
  const hasTrackRecord = trackRecord?.by_type && Object.keys(trackRecord.by_type).length > 0;

  const chartData = useMemo(() => {
    // Primary: use trackRecord if it has data (includes success rates)
    if (hasTrackRecord) {
      return Object.entries(trackRecord!.by_type)
        .map(([type, stats]) => ({
          type: type.charAt(0).toUpperCase() + type.slice(1),
          value: stats.success_rate,
          total: stats.total,
          fill: TYPE_COLORS[type] || '#6b7280',
          isRate: true,
        }))
        .filter(d => d.total > 0)
        .sort((a, b) => b.value - a.value);
    }
    // Fallback: compute counts from insights
    if (insights && insights.length > 0) {
      const counts: Record<string, number> = {};
      for (const insight of insights) {
        const type = insight.insight_type || 'other';
        counts[type] = (counts[type] || 0) + 1;
      }
      return Object.entries(counts)
        .map(([type, count]) => ({
          type: type.charAt(0).toUpperCase() + type.slice(1),
          value: count,
          total: count,
          fill: TYPE_COLORS[type] || '#6b7280',
          isRate: false,
        }))
        .sort((a, b) => b.value - a.value);
    }
    return [];
  }, [insights, trackRecord, hasTrackRecord]);

  return (
    <Card className="bg-card/80 backdrop-blur-sm border-border/50">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-primary" />
          <CardTitle className="text-base">Performance by Insight Type</CardTitle>
        </div>
        <CardDescription>{hasTrackRecord ? 'Success rate per category' : 'Insight count per category'}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <ChartSkeleton />
        ) : chartData.length === 0 ? (
          <EmptyChartState message="No insight type data yet" />
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 5, right: 40, left: 10, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" className="stroke-border/30" horizontal={false} />
              <XAxis
                type="number"
                tick={{ fontSize: 12 }}
                className="fill-muted-foreground"
                tickFormatter={hasTrackRecord ? (v: number) => `${(v * 100).toFixed(0)}%` : undefined}
                domain={hasTrackRecord ? [0, 1] : undefined}
                allowDecimals={!hasTrackRecord ? false : undefined}
              />
              <YAxis
                type="category"
                dataKey="type"
                tick={{ fontSize: 12 }}
                className="fill-muted-foreground"
                width={90}
              />
              <Tooltip
                wrapperStyle={tooltipWrapperStyle}
                cursor={{ fill: 'rgba(255, 255, 255, 0.05)' }}
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload;
                  return (
                    <div className="text-sm" style={tooltipStyle}>
                      <p className="font-medium text-white/90">{d.type}</p>
                      {d.isRate ? (
                        <p className="text-white/60">
                          Success Rate: {(d.value * 100).toFixed(1)}%
                        </p>
                      ) : (
                        <p className="text-white/60">
                          {d.value} insights
                        </p>
                      )}
                      <p className="text-white/60">{d.total} total</p>
                    </div>
                  );
                }}
              />
              <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================
// Outcome Tracking Stats
// ============================================

function OutcomeTrackingStats({ data, isLoading }: { data?: OutcomeSummary; isLoading: boolean }) {
  const miniStats = [
    {
      label: 'Currently Tracking',
      value: data?.currently_tracking ?? 0,
      icon: Eye,
      color: 'text-blue-500',
    },
    {
      label: 'Completed',
      value: data?.completed ?? 0,
      icon: CheckCircle2,
      color: 'text-green-500',
    },
    {
      label: 'Success Rate',
      value: formatPercent(data?.success_rate),
      icon: Target,
      color: 'text-emerald-500',
      isText: true,
    },
    {
      label: 'Avg Return',
      value: formatReturn(data?.avg_return_when_correct),
      icon: TrendingUp,
      color: 'text-primary',
      isText: true,
    },
  ];

  return (
    <Card className="bg-card/80 backdrop-blur-sm border-border/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">Outcome Tracking</CardTitle>
          </div>
          <Link
            href="/track-record"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Details
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
        <CardDescription>Real-time prediction validation</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="p-3 rounded-lg bg-muted/30">
                <Skeleton className="h-3 w-20 mb-2" />
                <Skeleton className="h-6 w-10" />
              </div>
            ))}
          </div>
        ) : !data || (data.total_tracked === 0 && data.completed === 0 && data.currently_tracking === 0) ? (
          <div className="flex items-center justify-center" style={{ height: 180 }}>
            <div className="text-center space-y-3">
              <Activity className="h-8 w-8 mx-auto opacity-30 text-muted-foreground" />
              <div>
                <p className="text-sm text-muted-foreground">Start tracking outcomes to see performance metrics</p>
                <p className="text-xs text-muted-foreground/60 mt-1">Outcomes are tracked automatically for insights with symbols</p>
              </div>
              <Link
                href="/track-record"
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                Go to Track Record
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {miniStats.map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.label}
                  className="p-3 rounded-lg bg-muted/20 border border-border/30"
                >
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1.5">
                    <Icon className={`h-3.5 w-3.5 ${item.color}`} />
                    {item.label}
                  </div>
                  <div className="text-lg font-bold">{item.value}</div>
                </div>
              );
            })}
          </div>
        )}

        {/* Direction breakdown */}
        {data?.by_direction && Object.keys(data.by_direction).length > 0 && (
          <div className="mt-3 pt-3 border-t border-border/30">
            <p className="text-xs text-muted-foreground mb-2">By Direction</p>
            <div className="flex gap-3">
              {Object.entries(data.by_direction).map(([dir, stats]) => (
                <div key={dir} className="flex items-center gap-2 text-xs">
                  <span className={dir.toLowerCase() === 'buy' ? 'text-green-500' : 'text-red-500'}>
                    {dir}
                  </span>
                  <span className="text-muted-foreground">
                    {stats.correct}/{stats.total}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================
// Top Symbols & Sectors
// ============================================

function TopSymbolsSectors({ patternsSummary, insights, isLoading }: { patternsSummary?: PatternsSummary; insights?: DeepInsight[]; isLoading: boolean }) {
  // Compute symbols and sectors from insights as fallback
  const insightSymbols = useMemo(() => {
    if (!insights || insights.length === 0) return [];
    const counts: Record<string, number> = {};
    for (const insight of insights) {
      if (insight.primary_symbol) {
        counts[insight.primary_symbol] = (counts[insight.primary_symbol] || 0) + 2; // weight primary higher
      }
      if (insight.related_symbols) {
        for (const sym of insight.related_symbols) {
          counts[sym] = (counts[sym] || 0) + 1;
        }
      }
    }
    return Object.entries(counts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([symbol]) => symbol);
  }, [insights]);

  const insightSectors = useMemo(() => {
    if (!insights || insights.length === 0) return [];
    const counts: Record<string, number> = {};
    for (const insight of insights) {
      if (insight.discovery_context?.top_sectors) {
        for (const sector of insight.discovery_context.top_sectors) {
          counts[sector] = (counts[sector] || 0) + 1;
        }
      }
    }
    return Object.entries(counts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 5)
      .map(([sector]) => sector);
  }, [insights]);

  // Use patterns summary if available, otherwise use insight-derived data
  const hasPatternData = patternsSummary && (patternsSummary.top_symbols.length > 0 || patternsSummary.top_sectors.length > 0);
  const topSymbols = hasPatternData ? patternsSummary!.top_symbols : insightSymbols;
  const topSectors = hasPatternData ? patternsSummary!.top_sectors : insightSectors;
  const hasAnyData = topSymbols.length > 0 || topSectors.length > 0;

  return (
    <Card className="bg-card/80 backdrop-blur-sm border-border/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Hash className="h-4 w-4 text-primary" />
            <CardTitle className="text-base">Top Symbols & Sectors</CardTitle>
          </div>
          <Link
            href="/patterns"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Patterns
            <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
        <CardDescription>
          {hasPatternData
            ? `${patternsSummary!.total} patterns (${patternsSummary!.active} active)`
            : hasAnyData
              ? 'Most referenced in insights'
              : 'Most referenced in patterns'
          }
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        ) : !hasAnyData ? (
          <EmptyChartState message="No symbol or sector data yet" height={180} />
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {/* Top Symbols */}
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">Symbols</p>
              <div className="space-y-1.5">
                {topSymbols.slice(0, 5).map((symbol, i) => (
                  <Link
                    key={symbol}
                    href={`/stocks/${symbol}`}
                    className="flex items-center gap-2 group"
                  >
                    <span className="text-xs text-muted-foreground w-4">{i + 1}.</span>
                    <Badge
                      variant="outline"
                      className="font-mono text-xs group-hover:bg-primary/10 transition-colors"
                    >
                      {symbol}
                    </Badge>
                  </Link>
                ))}
                {topSymbols.length === 0 && (
                  <p className="text-xs text-muted-foreground">None yet</p>
                )}
              </div>
            </div>

            {/* Top Sectors */}
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">Sectors</p>
              <div className="space-y-1.5">
                {topSectors.slice(0, 5).map((sector, i) => (
                  <div key={sector} className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground w-4">{i + 1}.</span>
                    <Badge variant="secondary" className="text-xs">
                      {sector}
                    </Badge>
                  </div>
                ))}
                {topSectors.length === 0 && (
                  <p className="text-xs text-muted-foreground">None yet</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Pattern type breakdown */}
        {patternsSummary?.by_type && Object.keys(patternsSummary.by_type).length > 0 && (
          <div className="mt-3 pt-3 border-t border-border/30">
            <p className="text-xs text-muted-foreground mb-2">Pattern Types</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(patternsSummary.by_type).map(([type, count]) => (
                <Badge key={type} variant="outline" className="text-xs gap-1">
                  {type.replace(/_/g, ' ').toLowerCase()}
                  <span className="text-muted-foreground">{count}</span>
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================
// Empty Chart State
// ============================================

function EmptyChartState({ message, height = 300 }: { message: string; height?: number }) {
  return (
    <div className="flex items-center justify-center text-muted-foreground" style={{ height }}>
      <div className="text-center space-y-2">
        <BarChart3 className="h-8 w-8 mx-auto opacity-30" />
        <p className="text-sm">{message}</p>
        <p className="text-xs opacity-60">Run an analysis to generate data</p>
      </div>
    </div>
  );
}

// ============================================
// Main Page Component
// ============================================

export default function DashboardPage() {
  // Fetch insights for stats & confidence distribution
  const { data: allInsightsData, isLoading: isLoadingInsights } = useRecentDeepInsights(100);

  // Fetch track record stats
  const { data: trackRecord, isLoading: isLoadingTrackRecord } = useQuery<TrackRecordStats>({
    queryKey: ['track-record'],
    queryFn: () => knowledgeApi.trackRecord(),
    staleTime: 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });

  // Fetch monthly trend
  const { data: monthlyTrend, isLoading: isLoadingTrend } = useQuery<MonthlyTrendResponse>({
    queryKey: ['track-record', 'monthly-trend'],
    queryFn: () => knowledgeApi.monthlyTrend(),
    staleTime: 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });

  // Fetch outcomes summary
  const { data: outcomesSummary, isLoading: isLoadingOutcomes } = useQuery<OutcomeSummary>({
    queryKey: ['outcomes', 'summary'],
    queryFn: () => outcomesApi.summary(),
    staleTime: 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });

  // Fetch patterns summary
  const { data: patternsSummary, isLoading: isLoadingPatterns } = useQuery<PatternsSummary>({
    queryKey: ['patterns', 'summary'],
    queryFn: () => knowledgeApi.patterns.summary(),
    staleTime: 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });

  // Analysis task hook
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

  // Compute stats from insights
  const stats = allInsightsData?.items ? computeStats(allInsightsData.items) : undefined;
  const hasData = allInsightsData?.items && allInsightsData.items.length > 0;
  const isLoading = isLoadingInsights && !hasData;

  // Last analysis time from most recent insight
  const lastAnalysisTime = allInsightsData?.items?.[0]?.created_at;

  // Tick every 30s so the "Last analysis: Xm ago" text stays fresh
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  // Memoize the formatted time; depends on tick so it recalculates periodically
  const lastAnalysisLabel = lastAnalysisTime ? formatRelativeTime(lastAnalysisTime) : null;

  const handleRunAnalysis = () => {
    startAnalysis({ max_insights: 5, deep_dive_count: 7 });
  };

  return (
    <div className="space-y-6">
      {/* Hero Section (slimmed down, no banner image) */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">Teletraan</h1>
            <MarketStatusBadge />
          </div>
          <p className="text-muted-foreground">
            AI-Powered Market Intelligence -- multi-agent deep analysis
          </p>
          {lastAnalysisLabel && (
            <p className="text-sm text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Last analysis: {lastAnalysisLabel}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <Link href="/insights">
            <Button variant="outline" size="lg">
              <BarChart3 className="h-4 w-4" />
              View Insights
            </Button>
          </Link>
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

      {/* Row 1: Quick Stats */}
      <AnalysisStatsCards stats={stats} isLoading={isLoading} />

      {/* Row 2: Monthly Trend + Action Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <MonthlyTrendChart data={monthlyTrend} insights={allInsightsData?.items} isLoading={isLoadingTrend && isLoadingInsights} />
        <ActionDistributionChart insights={allInsightsData?.items} trackRecord={trackRecord} isLoading={isLoadingInsights && isLoadingTrackRecord} />
      </div>

      {/* Row 3: Confidence Distribution + Performance by Type */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ConfidenceDistributionChart
          insights={allInsightsData?.items}
          isLoading={isLoadingInsights}
        />
        <PerformanceByTypeChart insights={allInsightsData?.items} trackRecord={trackRecord} isLoading={isLoadingInsights && isLoadingTrackRecord} />
      </div>

      {/* Row 4: Outcome Tracking + Top Symbols & Sectors */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <OutcomeTrackingStats data={outcomesSummary} isLoading={isLoadingOutcomes} />
        <TopSymbolsSectors patternsSummary={patternsSummary} insights={allInsightsData?.items} isLoading={isLoadingPatterns && isLoadingInsights} />
      </div>
    </div>
  );
}
