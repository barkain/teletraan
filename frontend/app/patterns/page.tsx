'use client';

import { useState, useEffect } from 'react';
import { PatternLibraryPanel } from '@/components/insights/pattern-library-panel';
import { Card, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { BookOpen } from 'lucide-react';
import { knowledgeApi } from '@/lib/api';
import type { KnowledgePattern, ConversationTheme } from '@/lib/types/knowledge';

export default function PatternsPage() {
  const [patterns, setPatterns] = useState<KnowledgePattern[]>([]);
  const [themes, setThemes] = useState<ConversationTheme[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

        setPatterns(patternsResponse.patterns || []);
        setThemes(themesResponse.themes || []);
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
    console.log('Pattern selected:', pattern);
    // In production, this could open a detail view or apply as a filter
  };

  const handleThemeSelect = (theme: ConversationTheme) => {
    console.log('Theme selected:', theme);
    // In production, this could filter insights by theme
  };

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

      {error ? (
        <Card className="min-h-[600px] flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            <p className="text-lg font-medium">{error}</p>
            <p className="text-sm mt-1">Please try again later</p>
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
    </div>
  );
}
