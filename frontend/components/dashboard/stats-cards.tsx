'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { DashboardStats } from '@/lib/hooks/use-market-data';
import { BarChart3, Lightbulb, Clock, Activity } from 'lucide-react';

interface StatsCardsProps {
  stats: DashboardStats | undefined;
  isLoading: boolean;
}

function formatLastAnalysis(dateString: string | null): string {
  if (!dateString) return 'Never';

  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

interface StatCardProps {
  title: string;
  value: string | number;
  description?: string;
  icon: React.ReactNode;
}

function StatCard({ title, value, description, icon }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <div className="h-4 w-4 text-muted-foreground">
          {icon}
        </div>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {description && (
          <p className="text-xs text-muted-foreground mt-1">{description}</p>
        )}
      </CardContent>
    </Card>
  );
}

function StatCardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-4" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-16 mb-1" />
        <Skeleton className="h-3 w-20" />
      </CardContent>
    </Card>
  );
}

export function StatsCards({ stats, isLoading }: StatsCardsProps) {
  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCardSkeleton />
        <StatCardSkeleton />
        <StatCardSkeleton />
        <StatCardSkeleton />
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <StatCard
        title="Total Stocks"
        value={stats?.total_stocks ?? 0}
        description="Tracked in portfolio"
        icon={<BarChart3 className="h-4 w-4" />}
      />
      <StatCard
        title="Active Insights"
        value={stats?.active_insights ?? 0}
        description="AI-generated insights"
        icon={<Lightbulb className="h-4 w-4" />}
      />
      <StatCard
        title="Last Analysis"
        value={formatLastAnalysis(stats?.last_analysis ?? null)}
        description="Most recent AI analysis"
        icon={<Clock className="h-4 w-4" />}
      />
      <StatCard
        title="Data Freshness"
        value={stats?.data_freshness ?? 'Unknown'}
        description="Market data status"
        icon={<Activity className="h-4 w-4" />}
      />
    </div>
  );
}
