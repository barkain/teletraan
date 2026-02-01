'use client';

import { use } from 'react';
import { InsightDetailView } from '@/components/insights/insight-detail-view';

interface InsightDetailPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default function InsightDetailPage({ params }: InsightDetailPageProps) {
  const resolvedParams = use(params);
  const insightId = parseInt(resolvedParams.id, 10);

  // Validate the ID
  if (isNaN(insightId) || insightId <= 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] space-y-4">
        <h1 className="text-2xl font-bold">Invalid Insight ID</h1>
        <p className="text-muted-foreground">
          The insight ID &quot;{resolvedParams.id}&quot; is not valid.
        </p>
        <a href="/insights" className="text-primary underline hover:no-underline">
          Return to Insights
        </a>
      </div>
    );
  }

  return <InsightDetailView insightId={insightId} />;
}
