'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { PatternLibraryPanel } from '@/components/insights/pattern-library-panel';
import { PatternStatsBar } from '@/components/patterns/pattern-stats-bar';
import { PatternDetailDrawer } from '@/components/patterns/pattern-detail-drawer';
import { Card, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { BookOpen, Brain, Sparkles, ArrowRight } from 'lucide-react';
import { knowledgeApi } from '@/lib/api';
import { useDeepInsights } from '@/lib/hooks/use-deep-insights';
import type { KnowledgePattern, ConversationTheme } from '@/lib/types/knowledge';

export default function PatternsPage() {
  const [patterns, setPatterns] = useState<KnowledgePattern[]>([]);
  const [themes, setThemes] = useState<ConversationTheme[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Detail drawer state
  const [selectedPattern, setSelectedPattern] = useState<KnowledgePattern | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Fetch insights count for progressive empty state
  const { data: insightsData } = useDeepInsights({ limit: 1 });
  const hasInsights = (insightsData?.total ?? 0) > 0;

  useEffect(() => {
    async function fetchData() {
      setIsLoading(true);
      setError(null);

      try {
        // Fetch patterns and themes in parallel
        const [patternsResponse, themesResponse] = await Promise.all([
          knowledgeApi.patterns.list(),
          knowledgeApi.themes.list(),
        ]);

        setPatterns(patternsResponse.items || []);
        setThemes(themesResponse.items || []);
      } catch (err) {
        console.error('Failed to fetch knowledge data:', err);
        setError('Failed to load patterns and themes');
        setPatterns([]);
        setThemes([]);
      } finally {
        setIsLoading(false);
      }
    }

    fetchData();
  }, []);

  const handlePatternSelect = (pattern: KnowledgePattern) => {
    setSelectedPattern(pattern);
    setDrawerOpen(true);
  };

  const handleThemeSelect = (theme: ConversationTheme) => {
    console.log('Theme selected:', theme);
  };

  // Progressive empty state: no patterns exist and not loading
  const showEmptyState = !isLoading && !error && patterns.length === 0;

  return (
    <div className="container py-6 max-w-7xl mx-auto">
      <Card className="mb-6">
        <CardHeader>
          <div className="flex items-center gap-2">
            <BookOpen className="h-6 w-6 text-primary" />
            <div>
              <CardTitle>Pattern Library</CardTitle>
              <CardDescription>
                Explore validated trading patterns and market themes identified by our analysis engine
              </CardDescription>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Stats Bar — only show when patterns exist */}
      {patterns.length > 0 && (
        <div className="mb-6">
          <PatternStatsBar patterns={patterns} />
        </div>
      )}

      {error ? (
        <Card className="min-h-[600px] flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            <p className="text-lg font-medium">{error}</p>
            <p className="text-sm mt-1">Please try again later</p>
          </div>
        </Card>
      ) : showEmptyState ? (
        /* Progressive empty state */
        <Card className="min-h-[400px] flex items-center justify-center">
          <div className="flex flex-col items-center text-center max-w-md px-6 py-12">
            {hasInsights ? (
              <>
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10 mb-4">
                  <Brain className="h-8 w-8 text-primary" />
                </div>
                <h3 className="text-lg font-semibold mb-2">No patterns yet</h3>
                <p className="text-sm text-muted-foreground mb-6">
                  Patterns are extracted from your analysis insights. Run a new autonomous
                  analysis to generate patterns from your existing insights.
                </p>
                <Button asChild>
                  <Link href="/">
                    <Sparkles className="h-4 w-4 mr-2" />
                    Run Autonomous Analysis
                  </Link>
                </Button>
              </>
            ) : (
              <>
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted mb-4">
                  <BookOpen className="h-8 w-8 text-muted-foreground" />
                </div>
                <h3 className="text-lg font-semibold mb-2">Build your pattern library</h3>
                <p className="text-sm text-muted-foreground mb-6">
                  Run your first autonomous analysis to start building your pattern library.
                  The analysis engine will identify recurring market patterns and track their
                  performance over time.
                </p>
                <Button asChild>
                  <Link href="/">
                    Get Started
                    <ArrowRight className="h-4 w-4 ml-2" />
                  </Link>
                </Button>
              </>
            )}
          </div>
        </Card>
      ) : (
        <PatternLibraryPanel
          patterns={patterns}
          themes={themes}
          isLoading={isLoading}
          onPatternSelect={handlePatternSelect}
          onThemeSelect={handleThemeSelect}
          className="min-h-[600px]"
        />
      )}

      {/* Pattern Detail Drawer */}
      <PatternDetailDrawer
        pattern={selectedPattern}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </div>
  );
}
