import ReportDetailClient from './report-detail-client';

// Workaround for Next.js static export: must return at least one param.
// The placeholder ID is handled gracefully by the client component (shows "not found").
export async function generateStaticParams() {
  return [{ id: '_' }];
}

interface ReportDetailPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default function ReportDetailPage({ params }: ReportDetailPageProps) {
  return <ReportDetailClient params={params} />;
}
