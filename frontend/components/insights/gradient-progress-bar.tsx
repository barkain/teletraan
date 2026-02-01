'use client';

import { cn } from '@/lib/utils';

interface GradientProgressBarProps {
  progress: number; // 0-100
  phaseName?: string;
  phaseDetails?: string;
  className?: string;
}

/**
 * Interpolate between two hex colors
 */
function interpolateColor(color1: string, color2: string, ratio: number): string {
  const hex1 = color1.replace('#', '');
  const hex2 = color2.replace('#', '');

  const r1 = parseInt(hex1.substring(0, 2), 16);
  const g1 = parseInt(hex1.substring(2, 4), 16);
  const b1 = parseInt(hex1.substring(4, 6), 16);

  const r2 = parseInt(hex2.substring(0, 2), 16);
  const g2 = parseInt(hex2.substring(2, 4), 16);
  const b2 = parseInt(hex2.substring(4, 6), 16);

  const r = Math.round(r1 + (r2 - r1) * ratio);
  const g = Math.round(g1 + (g2 - g1) * ratio);
  const b = Math.round(b1 + (b2 - b1) * ratio);

  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Get the progress bar color based on progress percentage
 * Gradient: white (0%) -> pale green (50%) -> dark green (100%)
 */
function getProgressColor(progress: number): string {
  const WHITE = '#FFFFFF';
  const PALE_GREEN = '#90EE90'; // lightgreen
  const DARK_GREEN = '#228B22'; // forestgreen

  if (progress <= 0) return WHITE;
  if (progress >= 100) return DARK_GREEN;

  if (progress < 50) {
    // Interpolate from white to pale green (0-50%)
    const ratio = progress / 50;
    return interpolateColor(WHITE, PALE_GREEN, ratio);
  }

  // Interpolate from pale green to dark green (50-100%)
  const ratio = (progress - 50) / 50;
  return interpolateColor(PALE_GREEN, DARK_GREEN, ratio);
}

/**
 * Get the gradient for the progress bar fill
 */
function getProgressGradient(progress: number): string {
  const currentColor = getProgressColor(progress);
  const startColor = getProgressColor(0);

  // Create a gradient from start to current position
  return `linear-gradient(90deg, ${startColor} 0%, ${currentColor} 100%)`;
}

export function GradientProgressBar({
  progress,
  phaseName,
  phaseDetails,
  className,
}: GradientProgressBarProps) {
  const clampedProgress = Math.max(0, Math.min(100, progress));
  const progressColor = getProgressColor(clampedProgress);
  const isComplete = clampedProgress >= 100;

  return (
    <div className={cn('w-full', className)}>
      {/* Phase info */}
      {(phaseName || phaseDetails) && (
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            {!isComplete && (
              <div
                className="h-2 w-2 rounded-full animate-pulse"
                style={{ backgroundColor: progressColor }}
              />
            )}
            <span className="text-sm font-medium">
              {phaseName || 'Processing...'}
            </span>
          </div>
          <span className="text-sm text-muted-foreground">
            {clampedProgress}%
          </span>
        </div>
      )}

      {/* Progress bar container */}
      <div className="relative h-3 w-full overflow-hidden rounded-full bg-secondary">
        {/* Progress fill with gradient */}
        <div
          className="h-full transition-all duration-500 ease-out rounded-full"
          style={{
            width: `${clampedProgress}%`,
            background: getProgressGradient(clampedProgress),
            boxShadow: isComplete
              ? '0 0 8px rgba(34, 139, 34, 0.5)'
              : undefined,
          }}
        />

        {/* Shimmer effect when in progress */}
        {!isComplete && clampedProgress > 0 && (
          <div
            className="absolute inset-0 overflow-hidden rounded-full"
            style={{ width: `${clampedProgress}%` }}
          >
            <div
              className="absolute inset-0 -translate-x-full animate-[shimmer_2s_infinite] bg-gradient-to-r from-transparent via-white/20 to-transparent"
            />
          </div>
        )}
      </div>

      {/* Phase details */}
      {phaseDetails && (
        <p className="mt-1 text-xs text-muted-foreground truncate">
          {phaseDetails}
        </p>
      )}
    </div>
  );
}

// Add shimmer animation to tailwind config or use inline style
// For now, adding via style tag in the component isn't ideal,
// but we can add this to globals.css:
// @keyframes shimmer {
//   100% { transform: translateX(100%); }
// }
