import { test, expect } from '@playwright/test';

// Mock insights covering all action types for filter testing
const mockInsightsAll = {
  items: [
    {
      id: 1,
      title: 'AAPL Strong Momentum',
      thesis: 'Apple showing strong upward momentum.',
      action: 'BUY',
      confidence: 0.85,
      insight_type: 'opportunity',
      time_horizon: 'medium-term',
      primary_symbol: 'AAPL',
      related_symbols: ['MSFT'],
      supporting_evidence: [
        { analyst: 'technical', finding: 'Golden cross on daily chart' },
      ],
      risk_factors: ['Market volatility'],
      analysts_involved: ['technical'],
      data_sources: ['yfinance'],
      created_at: new Date().toISOString(),
    },
    {
      id: 2,
      title: 'TSLA Strong Buy Setup',
      thesis: 'Tesla at critical support with bullish divergence.',
      action: 'STRONG_BUY',
      confidence: 0.91,
      insight_type: 'opportunity',
      time_horizon: 'short-term',
      primary_symbol: 'TSLA',
      related_symbols: [],
      supporting_evidence: [
        { analyst: 'technical', finding: 'Bullish divergence on RSI' },
      ],
      risk_factors: ['Earnings uncertainty'],
      analysts_involved: ['technical'],
      data_sources: ['yfinance'],
      created_at: new Date().toISOString(),
    },
    {
      id: 3,
      title: 'QQQ Sell Signal',
      thesis: 'Growth to value rotation accelerating.',
      action: 'SELL',
      confidence: 0.72,
      insight_type: 'rotation',
      time_horizon: 'short-term',
      primary_symbol: 'QQQ',
      related_symbols: ['XLF'],
      supporting_evidence: [
        { analyst: 'sector', finding: 'Value outperforming growth' },
      ],
      risk_factors: ['Fed pivot'],
      analysts_involved: ['sector'],
      data_sources: ['yfinance'],
      created_at: new Date().toISOString(),
    },
    {
      id: 4,
      title: 'SPY Strong Sell Warning',
      thesis: 'Broad market showing weakness across multiple indicators.',
      action: 'STRONG_SELL',
      confidence: 0.78,
      insight_type: 'risk',
      time_horizon: 'short-term',
      primary_symbol: 'SPY',
      related_symbols: ['VIX'],
      supporting_evidence: [
        { analyst: 'macro', finding: 'Yield curve inversion deepening' },
      ],
      risk_factors: ['Black swan events'],
      analysts_involved: ['macro'],
      data_sources: ['fred'],
      created_at: new Date().toISOString(),
    },
    {
      id: 5,
      title: 'NVDA Hold Signal',
      thesis: 'NVIDIA consolidating after strong run.',
      action: 'HOLD',
      confidence: 0.65,
      insight_type: 'opportunity',
      time_horizon: 'medium-term',
      primary_symbol: 'NVDA',
      related_symbols: ['AMD'],
      supporting_evidence: [
        { analyst: 'technical', finding: 'Trading in tight range' },
      ],
      risk_factors: ['Valuation risk'],
      analysts_involved: ['technical'],
      data_sources: ['yfinance'],
      created_at: new Date().toISOString(),
    },
    {
      id: 6,
      title: 'XLE Watch - Energy Rebound',
      thesis: 'Energy sector may see a rebound as oil stabilizes.',
      action: 'WATCH',
      confidence: 0.58,
      insight_type: 'macro',
      time_horizon: 'long-term',
      primary_symbol: 'XLE',
      related_symbols: ['XOM', 'CVX'],
      supporting_evidence: [
        { analyst: 'macro', finding: 'OPEC cuts supporting prices' },
      ],
      risk_factors: ['Demand uncertainty'],
      analysts_involved: ['macro'],
      data_sources: ['yfinance', 'fred'],
      created_at: new Date().toISOString(),
    },
  ],
  total: 6,
};

// Helper to set up standard API mocks for the insights page
async function setupInsightsMocks(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/deep-insights**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockInsightsAll),
    });
  });

  await page.route('**/api/v1/features/signals**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        signals: [
          { symbol: 'AAPL', feature_type: 'momentum', signal: 'bullish', value: 2.1, strength: 'strong' },
        ],
        count: 1,
        as_of: new Date().toISOString(),
      }),
    });
  });

  await page.route('**/api/v1/track-record/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });

  await page.route('**/api/v1/deep-insights/autonomous/status**', async (route) => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'No active analysis task' }),
    });
  });
}

test.describe('Insights Page', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('insights page loads with title and description', async ({ page }) => {
    await setupInsightsMocks(page);
    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    const title = page.locator('h1', { hasText: 'AI Insights' });
    await expect(title).toBeVisible({ timeout: 10000 });

    const description = page.locator('text=Deep analysis synthesized from multiple AI analysts');
    await expect(description).toBeVisible();
  });

  test('insights page shows result count', async ({ page }) => {
    await setupInsightsMocks(page);
    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    const resultCount = page.locator('text=/Showing \\d+ of \\d+ insights/');
    await expect(resultCount).toBeVisible({ timeout: 10000 });
  });

  test('insight cards render with correct data', async ({ page }) => {
    await setupInsightsMocks(page);
    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    await expect(page.locator('text=AAPL Strong Momentum')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=TSLA Strong Buy Setup')).toBeVisible();
    await expect(page.locator('text=QQQ Sell Signal')).toBeVisible();
  });

  test('insight card shows confidence percentage', async ({ page }) => {
    await setupInsightsMocks(page);
    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    await expect(page.locator('text=AAPL Strong Momentum')).toBeVisible({ timeout: 10000 });

    // Confidence values should be displayed as percentages (e.g. "85%")
    const confidenceValues = page.locator('text=/\\d+%/');
    const count = await confidenceValues.count();
    expect(count).toBeGreaterThan(0);
  });

  test('filter section has symbol search and dropdowns', async ({ page }) => {
    await setupInsightsMocks(page);
    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    const symbolInput = page.locator('input[placeholder*="Search by symbol"]');
    await expect(symbolInput).toBeVisible({ timeout: 10000 });

    const actionLabel = page.locator('text=Action');
    await expect(actionLabel.first()).toBeVisible();

    const typeLabel = page.locator('text=Type');
    await expect(typeLabel.first()).toBeVisible();
  });

  test('symbol search filters insights', async ({ page }) => {
    await page.route('**/api/v1/deep-insights**', async (route) => {
      const url = new URL(route.request().url());
      const symbol = url.searchParams.get('symbol');

      if (symbol === 'AAPL') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [mockInsightsAll.items[0]],
            total: 1,
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockInsightsAll),
        });
      }
    });

    await page.route('**/api/v1/features/signals**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ signals: [], count: 0, as_of: new Date().toISOString() }),
      });
    });
    await page.route('**/api/v1/track-record/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      });
    });

    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    await expect(page.locator('text=AAPL Strong Momentum')).toBeVisible({ timeout: 10000 });

    const symbolInput = page.locator('input[placeholder*="Search by symbol"]');
    await symbolInput.fill('AAPL');

    await page.waitForTimeout(1000);

    const filteredBadge = page.locator('text=Filtered');
    await expect(filteredBadge).toBeVisible({ timeout: 5000 });

    const clearButton = page.locator('button', { hasText: 'Clear Filters' });
    await expect(clearButton).toBeVisible();
  });

  test('empty state shows when no insights match filters', async ({ page }) => {
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      });
    });
    await page.route('**/api/v1/features/signals**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ signals: [], count: 0, as_of: new Date().toISOString() }),
      });
    });
    await page.route('**/api/v1/track-record/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      });
    });

    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    const emptyState = page.locator('text=No Insights Found');
    await expect(emptyState).toBeVisible({ timeout: 10000 });
  });

  test('statistical signals sidebar is visible', async ({ page }) => {
    await setupInsightsMocks(page);
    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    const signalsSidebar = page.locator('text=Statistical Signals');
    await expect(signalsSidebar).toBeVisible({ timeout: 10000 });
  });

  test('error state shows when API fails', async ({ page }) => {
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal Server Error' }),
      });
    });
    await page.route('**/api/v1/features/signals**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ signals: [], count: 0, as_of: new Date().toISOString() }),
      });
    });
    await page.route('**/api/v1/track-record/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      });
    });

    await page.goto('/insights');
    await page.waitForLoadState('networkidle');

    const errorMessage = page.locator('text=Error Loading Insights');
    await expect(errorMessage).toBeVisible({ timeout: 10000 });
  });

  test('loading skeletons show during data fetch', async ({ page }) => {
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockInsightsAll),
      });
    });
    await page.route('**/api/v1/features/signals**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ signals: [], count: 0, as_of: new Date().toISOString() }),
      });
    });
    await page.route('**/api/v1/track-record/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      });
    });

    const navigationPromise = page.goto('/insights');

    await page.waitForTimeout(500);

    const skeletons = page.locator('[class*="skeleton"], .animate-pulse');
    const skeletonCount = await skeletons.count();
    expect(skeletonCount).toBeGreaterThan(0);

    await navigationPromise;
    await page.waitForLoadState('networkidle');
  });
});
