'use client';

import { use } from 'react';
import Link from 'next/link';
import { InsightDetailView } from '@/components/insights/insight-detail-view';

interface InsightDetailClientProps {
  params: Promise<{
    id: string;
  }>;
}

export default function InsightDetailClient({ params }: InsightDetailClientProps) {
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
        <Link href="/insights" className="text-primary underline hover:no-underline">
          Return to Insights
        </Link>
      </div>
    );
  }

  return <InsightDetailView insightId={insightId} />;
}
