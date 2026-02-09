import { formatDistanceToNow } from 'date-fns';
import { Clock, ExternalLink, AlertTriangle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ResearchStatusBadge } from './research-status-badge';
import { ResearchTypeBadge } from './research-type-badge';
import type { FollowUpResearch } from '@/lib/types/research';

interface ResearchListProps {
  items: FollowUpResearch[];
  onSelect: (research: FollowUpResearch) => void;
}

function ResearchCard({
  research,
  onClick,
}: {
  research: FollowUpResearch;
  onClick: () => void;
}) {
  const symbols = (research.parameters?.symbols as string[]) || [];

  return (
    <Card
      className="hover:shadow-lg transition-shadow cursor-pointer"
      onClick={onClick}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <ResearchTypeBadge type={research.research_type} />
              <ResearchStatusBadge status={research.status} />
            </div>
            <CardTitle className="text-lg line-clamp-2">{research.query}</CardTitle>
          </div>
          <div className="text-right text-sm text-muted-foreground shrink-0">
            <div className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              <span>
                {formatDistanceToNow(new Date(research.created_at), {
                  addSuffix: true,
                })}
              </span>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 flex-wrap">
            {symbols.map((symbol) => (
              <Badge key={symbol} variant="secondary" className="text-xs">
                {symbol}
              </Badge>
            ))}
          </div>
          <div className="shrink-0">
            {research.status === 'COMPLETED' && research.result_insight_id && (
              <span className="text-sm text-primary flex items-center gap-1">
                <ExternalLink className="h-3 w-3" />
                View result
              </span>
            )}
            {research.status === 'FAILED' && research.error_message && (
              <span className="text-sm text-destructive flex items-center gap-1 max-w-[200px] truncate">
                <AlertTriangle className="h-3 w-3 shrink-0" />
                <span className="truncate">{research.error_message}</span>
              </span>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function ResearchList({ items, onSelect }: ResearchListProps) {
  return (
    <div className="space-y-4">
      {items.map((research) => (
        <ResearchCard
          key={research.id}
          research={research}
          onClick={() => onSelect(research)}
        />
      ))}
    </div>
  );
}
