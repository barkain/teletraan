'use client';

import { useState, useMemo } from 'react';
import {
  FlaskConical,
  Filter,
  Loader2,
  CheckCircle,
  XCircle,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ResearchList } from '@/components/research/research-list';
import { ResearchDetail } from '@/components/research/research-detail';
import { useResearchList } from '@/lib/hooks/use-research';
import type { FollowUpResearch, ResearchStatus, ResearchType } from '@/lib/types/research';

const statusOptions = [
  { value: 'all', label: 'All Status' },
  { value: 'PENDING', label: 'Pending' },
  { value: 'RUNNING', label: 'Running' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'CANCELLED', label: 'Cancelled' },
];

const typeOptions = [
  { value: 'all', label: 'All Types' },
  { value: 'DEEP_DIVE', label: 'Deep Dive' },
  { value: 'SCENARIO_ANALYSIS', label: 'Scenario Analysis' },
  { value: 'WHAT_IF', label: 'What If' },
  { value: 'CORRELATION_CHECK', label: 'Correlation' },
  { value: 'SECTOR_DEEP_DIVE', label: 'Sector Deep Dive' },
  { value: 'TECHNICAL_FOCUS', label: 'Technical Focus' },
  { value: 'MACRO_IMPACT', label: 'Macro Impact' },
];

function ResearchSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <Card key={i}>
          <div className="p-6">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex gap-2 mb-2">
                  <Skeleton className="h-5 w-20" />
                  <Skeleton className="h-5 w-16" />
                </div>
                <Skeleton className="h-6 w-3/4" />
              </div>
              <Skeleton className="h-4 w-24" />
            </div>
            <div className="flex gap-2 mt-3">
              <Skeleton className="h-5 w-14" />
              <Skeleton className="h-5 w-14" />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <FlaskConical className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No Research Yet</CardTitle>
        <CardDescription className="max-w-sm">
          Research is triggered from insight conversations or can be launched manually.
          Start a conversation about an insight to generate follow-up research.
        </CardDescription>
      </CardContent>
    </Card>
  );
}

function StatsBar({
  items,
}: {
  items: FollowUpResearch[];
}) {
  const stats = useMemo(() => {
    const total = items.length;
    const running = items.filter((i) => i.status === 'RUNNING').length;
    const pending = items.filter((i) => i.status === 'PENDING').length;
    const completed = items.filter((i) => i.status === 'COMPLETED').length;
    const failed = items.filter((i) => i.status === 'FAILED').length;
    return { total, running, pending, completed, failed };
  }, [items]);

  return (
    <div className="flex items-center gap-4 flex-wrap">
      <span className="text-sm text-muted-foreground">
        {stats.total} total
      </span>
      {(stats.running > 0 || stats.pending > 0) && (
        <span className="text-sm text-blue-600 dark:text-blue-400 flex items-center gap-1">
          <Loader2 className="h-3 w-3 animate-spin" />
          {stats.running + stats.pending} active
        </span>
      )}
      {stats.completed > 0 && (
        <span className="text-sm text-green-600 dark:text-green-400 flex items-center gap-1">
          <CheckCircle className="h-3 w-3" />
          {stats.completed} completed
        </span>
      )}
      {stats.failed > 0 && (
        <span className="text-sm text-red-600 dark:text-red-400 flex items-center gap-1">
          <XCircle className="h-3 w-3" />
          {stats.failed} failed
        </span>
      )}
    </div>
  );
}

export default function ResearchPage() {
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [selectedResearch, setSelectedResearch] = useState<FollowUpResearch | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  // Build query params
  const queryParams = {
    limit: 50,
    ...(statusFilter !== 'all' && { status: statusFilter as ResearchStatus }),
    ...(typeFilter !== 'all' && { research_type: typeFilter as ResearchType }),
  };

  const { data, isLoading, error } = useResearchList(queryParams);
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const handleSelect = (research: FollowUpResearch) => {
    setSelectedResearch(research);
    setDetailOpen(true);
  };

  const handleClearFilters = () => {
    setStatusFilter('all');
    setTypeFilter('all');
  };

  const hasFilters = statusFilter !== 'all' || typeFilter !== 'all';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2">
          <FlaskConical className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Research</h1>
        </div>
        <p className="text-muted-foreground mt-1">
          Follow-up research spawned from insight conversations
        </p>
        {!isLoading && items.length > 0 && (
          <div className="mt-2">
            <StatsBar items={items} />
          </div>
        )}
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap gap-4 items-end">
            <div className="w-[180px]">
              <label className="text-sm font-medium mb-2 block">Status</label>
              <Select
                value={statusFilter}
                onValueChange={(value) => setStatusFilter(value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {statusOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[180px]">
              <label className="text-sm font-medium mb-2 block">Type</label>
              <Select
                value={typeFilter}
                onValueChange={(value) => setTypeFilter(value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {typeOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {hasFilters && (
              <Button variant="ghost" size="sm" onClick={handleClearFilters}>
                Clear Filters
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Results Count */}
      {!isLoading && (
        <div className="flex items-center gap-2">
          <p className="text-sm text-muted-foreground">
            {total === 0
              ? 'No research found'
              : `Showing ${items.length} of ${total} research items`}
          </p>
          {hasFilters && (
            <Badge variant="secondary" className="gap-1">
              <Filter className="h-3 w-3" />
              Filtered
            </Badge>
          )}
        </div>
      )}

      {/* Research List */}
      {isLoading ? (
        <ResearchSkeleton />
      ) : error ? (
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <CardTitle className="text-lg mb-2 text-destructive">
              Error Loading Research
            </CardTitle>
            <CardDescription>
              {error instanceof Error ? error.message : 'An unexpected error occurred'}
            </CardDescription>
          </CardContent>
        </Card>
      ) : items.length === 0 ? (
        <EmptyState />
      ) : (
        <ResearchList items={items} onSelect={handleSelect} />
      )}

      {/* Research Detail Sheet */}
      <ResearchDetail
        research={selectedResearch}
        open={detailOpen}
        onOpenChange={setDetailOpen}
      />
    </div>
  );
}
