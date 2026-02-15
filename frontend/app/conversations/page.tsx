'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { formatDistanceToNow } from 'date-fns';
import {
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  Filter,
  Lightbulb,
  Clock,
  Archive,
  CheckCircle,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ConnectionError } from '@/components/ui/empty-state';
import {
  useAllConversations,
  type InsightConversation,
} from '@/lib/hooks/use-insight-conversation';
import { useDeepInsights } from '@/lib/hooks/use-deep-insights';

const ITEMS_PER_PAGE = 20;

const statusOptions = [
  { value: 'all', label: 'All Status' },
  { value: 'ACTIVE', label: 'Active' },
  { value: 'ARCHIVED', label: 'Archived' },
  { value: 'RESOLVED', label: 'Resolved' },
];

const statusConfig: Record<string, { icon: typeof MessageSquare; color: string; label: string }> = {
  ACTIVE: { icon: MessageSquare, color: 'bg-green-500', label: 'Active' },
  ARCHIVED: { icon: Archive, color: 'bg-gray-500', label: 'Archived' },
  RESOLVED: { icon: CheckCircle, color: 'bg-blue-500', label: 'Resolved' },
};

function ConversationCard({
  conversation,
  insightTitle,
  onClick,
}: {
  conversation: InsightConversation;
  insightTitle?: string;
  onClick: () => void;
}) {
  const status = statusConfig[conversation.status] || statusConfig.ACTIVE;
  const StatusIcon = status.icon;

  return (
    <Card
      className="hover:shadow-lg transition-shadow cursor-pointer"
      onClick={onClick}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <Badge className={`${status.color} text-white`}>
                <StatusIcon className="w-3 h-3 mr-1" />
                {status.label}
              </Badge>
              {conversation.message_count > 0 && (
                <Badge variant="secondary">
                  {conversation.message_count} messages
                </Badge>
              )}
              {conversation.modification_count > 0 && (
                <Badge variant="outline" className="border-amber-500 text-amber-600">
                  {conversation.modification_count} modifications
                </Badge>
              )}
            </div>
            <CardTitle className="text-lg truncate">{conversation.title}</CardTitle>
            {insightTitle && (
              <div className="flex items-center gap-1 mt-1 text-sm text-muted-foreground">
                <Lightbulb className="h-3 w-3" />
                <span className="truncate">{insightTitle}</span>
              </div>
            )}
          </div>
          <div className="text-right text-sm text-muted-foreground shrink-0">
            <div className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              <span>{formatDistanceToNow(new Date(conversation.updated_at), { addSuffix: true })}</span>
            </div>
          </div>
        </div>
      </CardHeader>
      {conversation.summary && (
        <CardContent className="pt-0">
          <p className="text-sm text-muted-foreground line-clamp-2">
            {conversation.summary}
          </p>
        </CardContent>
      )}
    </Card>
  );
}

function ConversationsListSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex gap-2 mb-2">
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-5 w-24" />
                </div>
                <Skeleton className="h-6 w-3/4" />
                <Skeleton className="h-4 w-1/2 mt-1" />
              </div>
              <Skeleton className="h-4 w-24" />
            </div>
          </CardHeader>
        </Card>
      ))}
    </div>
  );
}

function EmptyState() {
  const router = useRouter();

  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <MessageSquare className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No Conversations Yet</CardTitle>
        <CardDescription className="max-w-sm mb-4">
          Start a conversation about any insight to explore it deeper, ask questions,
          or propose modifications.
        </CardDescription>
        <Button onClick={() => router.push('/insights')}>
          <Lightbulb className="h-4 w-4 mr-2" />
          Browse Insights
        </Button>
      </CardContent>
    </Card>
  );
}

function Pagination({
  currentPage,
  totalPages,
  onPageChange,
}: {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-2 mt-6">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage <= 1}
      >
        <ChevronLeft className="h-4 w-4" />
        Previous
      </Button>
      <span className="text-sm text-muted-foreground px-4">
        Page {currentPage} of {totalPages}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage >= totalPages}
      >
        Next
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}

export default function ConversationsPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // Build query params
  const queryParams = {
    limit: ITEMS_PER_PAGE,
    offset: (page - 1) * ITEMS_PER_PAGE,
    ...(statusFilter !== 'all' && { status: statusFilter }),
  };

  const { conversations, total, isLoading, error } = useAllConversations(queryParams);

  // Get all insights for mapping conversation to insight title
  // Note: In production, this should be optimized with a dedicated endpoint
  const { data: insightsData } = useDeepInsights({ limit: 100 });

  const insightMap = new Map(
    insightsData?.items?.map((insight) => [insight.id, insight.title]) ?? []
  );

  const totalPages = Math.ceil(total / ITEMS_PER_PAGE);

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleConversationClick = (conversation: InsightConversation) => {
    // Navigate to the insight detail page with the conversation selected
    router.push(`/insights?id=${conversation.deep_insight_id}&conversation=${conversation.id}`);
  };

  const handleClearFilters = () => {
    setStatusFilter('all');
    setPage(1);
  };

  const hasFilters = statusFilter !== 'all';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2">
          <MessageSquare className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Conversations</h1>
        </div>
        <p className="text-muted-foreground mt-1">
          Explore and continue your discussions about market insights
        </p>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap gap-4 items-end">
            <div className="w-[180px]">
              <label className="text-sm font-medium mb-2 block">Status</label>
              <Select
                value={statusFilter}
                onValueChange={(value) => {
                  setStatusFilter(value);
                  setPage(1);
                }}
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
            {total === 0 ? 'No conversations found' : `Showing ${conversations.length} of ${total} conversations`}
          </p>
          {hasFilters && (
            <Badge variant="secondary" className="gap-1">
              <Filter className="h-3 w-3" />
              Filtered
            </Badge>
          )}
        </div>
      )}

      {/* Conversations List */}
      {isLoading ? (
        <ConversationsListSkeleton />
      ) : error ? (
        <ConnectionError error={error} />
      ) : conversations.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <div className="space-y-4">
            {conversations.map((conversation) => (
              <ConversationCard
                key={conversation.id}
                conversation={conversation}
                insightTitle={insightMap.get(conversation.deep_insight_id)}
                onClick={() => handleConversationClick(conversation)}
              />
            ))}
          </div>

          {/* Pagination */}
          <Pagination
            currentPage={page}
            totalPages={totalPages}
            onPageChange={handlePageChange}
          />
        </>
      )}
    </div>
  );
}
