import InsightDetailClient from './insight-detail-client';

// Workaround for Next.js static export: must return at least one param.
// The placeholder ID is handled gracefully by the client component (shows "invalid").
export async function generateStaticParams() {
  return [{ id: '_' }];
}

interface InsightDetailPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default function InsightDetailPage({ params }: InsightDetailPageProps) {
  return <InsightDetailClient params={params} />;
}
