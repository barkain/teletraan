'use client';

import { TrendingUp, BarChart3, Volume2, Calendar, Lightbulb, Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';

interface SuggestedPromptsProps {
  onSelect: (prompt: string) => void;
  className?: string;
}

interface SuggestedPrompt {
  icon: React.ReactNode;
  text: string;
  category: 'analysis' | 'technical' | 'volume' | 'economic' | 'general';
}

const suggestions: SuggestedPrompt[] = [
  {
    icon: <TrendingUp className="w-4 h-4" />,
    text: "What's the best performing sector today?",
    category: 'analysis',
  },
  {
    icon: <BarChart3 className="w-4 h-4" />,
    text: 'Analyze AAPL technical indicators',
    category: 'technical',
  },
  {
    icon: <Volume2 className="w-4 h-4" />,
    text: 'Are there any unusual volume patterns?',
    category: 'volume',
  },
  {
    icon: <Calendar className="w-4 h-4" />,
    text: 'What economic indicators should I watch?',
    category: 'economic',
  },
  {
    icon: <Lightbulb className="w-4 h-4" />,
    text: 'Give me a market summary for today',
    category: 'general',
  },
  {
    icon: <Search className="w-4 h-4" />,
    text: 'Which tech stocks are oversold?',
    category: 'technical',
  },
];

const categoryColors: Record<SuggestedPrompt['category'], string> = {
  analysis: 'hover:border-blue-500/50 hover:bg-blue-500/5',
  technical: 'hover:border-purple-500/50 hover:bg-purple-500/5',
  volume: 'hover:border-amber-500/50 hover:bg-amber-500/5',
  economic: 'hover:border-green-500/50 hover:bg-green-500/5',
  general: 'hover:border-gray-500/50 hover:bg-gray-500/5',
};

export function SuggestedPrompts({ onSelect, className }: SuggestedPromptsProps) {
  return (
    <div className={cn('space-y-3', className)}>
      <div className="text-center">
        <h3 className="text-lg font-semibold mb-1">How can I help you?</h3>
        <p className="text-sm text-muted-foreground">
          Ask me about market analysis, stock data, or technical indicators
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl mx-auto">
        {suggestions.map((suggestion, index) => (
          <Button
            key={index}
            variant="outline"
            className={cn(
              'h-auto py-3 px-4 justify-start gap-3 text-left transition-colors',
              categoryColors[suggestion.category]
            )}
            onClick={() => onSelect(suggestion.text)}
          >
            <span className="text-muted-foreground flex-shrink-0">
              {suggestion.icon}
            </span>
            <span className="text-sm">{suggestion.text}</span>
          </Button>
        ))}
      </div>
    </div>
  );
}
