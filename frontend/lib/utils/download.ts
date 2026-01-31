/**
 * Utility functions for downloading files from the API.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface DownloadOptions {
  /** Custom filename override (if not using server-provided name) */
  filename?: string;
  /** Callback when download starts */
  onStart?: () => void;
  /** Callback when download completes */
  onComplete?: () => void;
  /** Callback when download fails */
  onError?: (error: Error) => void;
}

/**
 * Download a file from a URL and trigger browser download.
 */
export async function downloadFile(
  url: string,
  options: DownloadOptions = {}
): Promise<void> {
  const { filename, onStart, onComplete, onError } = options;

  try {
    onStart?.();

    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`Download failed: ${response.status} ${response.statusText}`);
    }

    const blob = await response.blob();

    // Try to get filename from Content-Disposition header
    let downloadFilename = filename;
    if (!downloadFilename) {
      const contentDisposition = response.headers.get('Content-Disposition');
      if (contentDisposition) {
        const match = contentDisposition.match(/filename=([^;]+)/);
        if (match) {
          downloadFilename = match[1].replace(/"/g, '').trim();
        }
      }
    }

    // Fallback filename based on URL
    if (!downloadFilename) {
      const urlPath = new URL(url).pathname;
      downloadFilename = urlPath.split('/').pop() || 'download';
    }

    // Create download link
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = downloadFilename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(downloadUrl);

    onComplete?.();
  } catch (error) {
    const err = error instanceof Error ? error : new Error(String(error));
    onError?.(err);
    throw err;
  }
}

/**
 * Build export URL for stock data.
 */
export function buildStockExportUrl(
  symbol: string,
  format: 'csv' | 'json',
  options: {
    startDate?: string;
    endDate?: string;
    includeIndicators?: boolean;
  } = {}
): string {
  const params = new URLSearchParams();

  if (options.startDate) {
    params.set('start_date', options.startDate);
  }
  if (options.endDate) {
    params.set('end_date', options.endDate);
  }
  if (options.includeIndicators !== undefined) {
    params.set('include_indicators', String(options.includeIndicators));
  }

  const queryString = params.toString();
  return `${API_URL}/api/export/stocks/${symbol}/${format}${queryString ? `?${queryString}` : ''}`;
}

/**
 * Build export URL for insights.
 */
export function buildInsightsExportUrl(
  format: 'csv' | 'json',
  options: {
    insightType?: string;
    severity?: string;
    symbol?: string;
    includeAnnotations?: boolean;
  } = {}
): string {
  const params = new URLSearchParams();

  if (options.insightType) {
    params.set('insight_type', options.insightType);
  }
  if (options.severity) {
    params.set('severity', options.severity);
  }
  if (options.symbol) {
    params.set('symbol', options.symbol);
  }
  if (options.includeAnnotations !== undefined) {
    params.set('include_annotations', String(options.includeAnnotations));
  }

  const queryString = params.toString();
  return `${API_URL}/api/export/insights/${format}${queryString ? `?${queryString}` : ''}`;
}

/**
 * Build export URL for complete stock analysis.
 */
export function buildAnalysisExportUrl(
  symbol: string,
  format: 'csv' | 'json',
  options: {
    startDate?: string;
    endDate?: string;
    includeIndicators?: boolean;
    includeInsights?: boolean;
  } = {}
): string {
  const params = new URLSearchParams();
  params.set('format', format);

  if (options.startDate) {
    params.set('start_date', options.startDate);
  }
  if (options.endDate) {
    params.set('end_date', options.endDate);
  }
  if (options.includeIndicators !== undefined) {
    params.set('include_indicators', String(options.includeIndicators));
  }
  if (options.includeInsights !== undefined) {
    params.set('include_insights', String(options.includeInsights));
  }

  return `${API_URL}/api/export/analysis/${symbol}?${params.toString()}`;
}
