'use client';

import { Card, CardContent } from '@/components/ui/card';
import type { KnowledgePattern } from '@/lib/types/knowledge';
import { BarChart3, CheckCircle, Target, Layers } from 'lucide-react';

interface PatternStatsBarProps {
  patterns: KnowledgePattern[];
}

function computeStats(patterns: KnowledgePattern[]) {
  const total = patterns.length;

  const active = patterns.filter((p) => p.is_active).length;

  const avgSuccessRate =
    total > 0
      ? patterns.reduce((sum, p) => sum + (p.success_rate ?? 0), 0) / total
      : 0;

  const typeCounts: Record<string, number> = {};
  for (const p of patterns) {
    typeCounts[p.pattern_type] = (typeCounts[p.pattern_type] ?? 0) + 1;
  }
  const mostCommonType =
    Object.entries(typeCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—';

  return { total, active, avgSuccessRate, mostCommonType };
}

function formatPatternType(type: string): string {
  return type
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
}

export function PatternStatsBar({ patterns }: PatternStatsBarProps) {
  const { total, active, avgSuccessRate, mostCommonType } =
    computeStats(patterns);

  const stats = [
    {
      label: 'Total Patterns',
      value: total.toString(),
      icon: Layers,
    },
    {
      label: 'Active',
      value: active.toString(),
      icon: CheckCircle,
    },
    {
      label: 'Avg Success Rate',
      value: `${(avgSuccessRate * 100).toFixed(1)}%`,
      icon: Target,
    },
    {
      label: 'Most Common Type',
      value: mostCommonType === '—' ? '—' : formatPatternType(mostCommonType),
      icon: BarChart3,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {stats.map((stat) => (
        <Card key={stat.label} className="py-4">
          <CardContent className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
              <stat.icon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground">{stat.label}</p>
              <p className="truncate text-lg font-semibold leading-tight">
                {stat.value}
              </p>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
