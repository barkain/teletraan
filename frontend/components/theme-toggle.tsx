'use client';

import * as React from 'react';
import { Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface ThemeToggleProps {
  variant?: 'default' | 'header';
}

export function ThemeToggle({ variant = 'default' }: ThemeToggleProps) {
  const { theme, setTheme } = useTheme();

  const toggleTheme = () => {
    setTheme(theme === 'dark' ? 'light' : 'dark');
  };

  const isHeader = variant === 'header';

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      className={cn(
        isHeader && 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-white/80 dark:hover:text-white dark:hover:bg-white/10'
      )}
    >
      <Sun
        className={cn(
          'h-5 w-5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0',
          isHeader && 'h-4 w-4'
        )}
      />
      <Moon
        className={cn(
          'absolute h-5 w-5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100',
          isHeader && 'h-4 w-4'
        )}
      />
      <span className="sr-only">Toggle theme</span>
    </Button>
  );
}
