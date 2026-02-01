'use client';

import { TrackRecordDashboard } from '@/components/insights/track-record-dashboard';

export default function TrackRecordPage() {
  return (
    <div className="container py-6 max-w-7xl mx-auto">
      <TrackRecordDashboard lookbackDays={90} />
    </div>
  );
}
