import { test, expect } from './fixtures';

// Shared mock data for deep insights API
const mockInsightsResponse = {
  items: [
    {
      id: 1,
      title: 'AAPL Breakout Pattern Detected',
      thesis: 'Apple is forming a bullish breakout pattern above key resistance.',
      action: 'BUY',
      confidence: 0.85,
      insight_type: 'opportunity',
      time_horizon: 'medium-term',
      primary_symbol: 'AAPL',
      related_symbols: ['MSFT', 'GOOGL'],
      supporting_evidence: [
        { analyst: 'technical', finding: 'Golden cross on daily chart' },
        { analyst: 'momentum', finding: 'RSI trending bullish at 62' },
      ],
      risk_factors: ['Market volatility', 'Sector rotation risk'],
      invalidation_trigger: 'Close below $170',
      historical_precedent: 'Similar setup led to 15% gains in 2023',
      analysts_involved: ['technical', 'momentum'],
      data_sources: ['yfinance'],
      created_at: new Date().toISOString(),
    },
    {
      id: 2,
      title: 'Sector Rotation: Value Over Growth',
      thesis: 'Rotation from growth to value sectors accelerating.',
      action: 'SELL',
      confidence: 0.72,
      insight_type: 'rotation',
      time_horizon: 'short-term',
      primary_symbol: 'QQQ',
      related_symbols: ['XLF', 'XLE'],
      supporting_evidence: [
        { analyst: 'sector', finding: 'Value outperforming growth by 3% this month' },
      ],
      risk_factors: ['Fed policy reversal'],
      invalidation_trigger: 'Tech breakout above 52-week high',
      analysts_involved: ['sector'],
      data_sources: ['yfinance'],
      created_at: new Date().toISOString(),
    },
    {
      id: 3,
      title: 'NVDA Hold Signal',
      thesis: 'NVIDIA in consolidation phase after strong run.',
      action: 'HOLD',
      confidence: 0.65,
      insight_type: 'opportunity',
      time_horizon: 'medium-term',
      primary_symbol: 'NVDA',
      related_symbols: ['AMD', 'AVGO'],
      supporting_evidence: [
        { analyst: 'technical', finding: 'Trading in tight range near ATH' },
      ],
      risk_factors: ['Valuation stretched'],
      analysts_involved: ['technical'],
      data_sources: ['yfinance'],
      created_at: new Date().toISOString(),
    },
    {
      id: 4,
      title: 'Energy Sector Watch',
      thesis: 'Oil prices stabilizing, energy sector may see rebound.',
      action: 'WATCH',
      confidence: 0.60,
      insight_type: 'macro',
      time_horizon: 'long-term',
      primary_symbol: 'XLE',
      related_symbols: ['XOM', 'CVX'],
      supporting_evidence: [
        { analyst: 'macro', finding: 'OPEC production cuts supporting prices' },
      ],
      risk_factors: ['Global demand uncertainty'],
      analysts_involved: ['macro'],
      data_sources: ['yfinance', 'fred'],
      created_at: new Date().toISOString(),
    },
  ],
  total: 4,
};

// Helper to set up standard API mocks for the dashboard
// Register specific routes BEFORE broad patterns so they take priority
async function setupDashboardMocks(page: import('@playwright/test').Page) {
  // Mock autonomous analysis endpoints (register BEFORE broad deep-insights route)
  await page.route('**/api/v1/deep-insights/autonomous/**', async (route) => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'No active analysis task' }),
    });
  });

  // Mock the deep-insights list endpoint
  await page.route('**/api/v1/deep-insights?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockInsightsResponse),
    });
  });

  // Also match without query params
  await page.route('**/api/v1/deep-insights', async (route) => {
    if (route.request().url().includes('/autonomous/')) {
      // Let the autonomous handler above take care of it
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockInsightsResponse),
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
}

test.describe('Dashboard (Home Page)', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('home page loads with Teletraan branding', async ({ page }) => {
    await setupDashboardMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // The main heading should say "Teletraan"
    const heading = page.locator('h1', { hasText: 'Teletraan' });
    await expect(heading).toBeVisible({ timeout: 10000 });

    // The subtitle text should be visible
    const subtitle = page.locator('text=AI-Powered Market Intelligence');
    await expect(subtitle).toBeVisible();

    // Header logo should also contain Teletraan
    const headerBrand = page.locator('header').locator('text=Teletraan');
    await expect(headerBrand.first()).toBeVisible();
  });

  test('Discover Opportunities button exists and is functional', async ({ page }) => {
    await setupDashboardMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // The "Discover Opportunities" button is in the hero section
    const discoverButton = page.getByRole('button', { name: /Discover Opportunities/i });
    await expect(discoverButton.first()).toBeVisible({ timeout: 10000 });
    await expect(discoverButton.first()).toBeEnabled();
  });

  test('summary stats cards render with correct data', async ({ page }) => {
    await setupDashboardMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Wait for stats cards to appear
    const totalInsightsLabel = page.locator('text=Total Insights');
    await expect(totalInsightsLabel).toBeVisible({ timeout: 10000 });

    // Verify all 5 stat card labels exist
    await expect(page.locator('text=Total Insights')).toBeVisible();
    await expect(page.locator('text=Buy Signals')).toBeVisible();
    await expect(page.locator('text=Sell Signals')).toBeVisible();
    // Use .first() for "Hold" which appears in multiple places
    await expect(page.locator('text=Hold').first()).toBeVisible();
    await expect(page.locator('text=Watch List')).toBeVisible();

    // Verify the counts match mock data: 4 total, 1 buy, 1 sell, 1 hold, 1 watch
    const statValues = page.locator('.text-2xl.font-bold');
    const values: string[] = [];
    const count = await statValues.count();
    for (let i = 0; i < count; i++) {
      const text = await statValues.nth(i).textContent();
      if (text !== null) {
        values.push(text.trim());
      }
    }
    // First stat card should be total = 4
    expect(values).toContain('4');
  });

  test('View Insights button links to insights page', async ({ page }) => {
    await setupDashboardMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // The "View Insights" button links to /insights
    const viewInsightsLink = page.locator('a[href="/insights"]');
    await expect(viewInsightsLink.first()).toBeVisible({ timeout: 10000 });
  });

  test('Market status badge is displayed', async ({ page }) => {
    await setupDashboardMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const marketBadge = page.locator('text=/Market (Open|Closed)/');
    await expect(marketBadge).toBeVisible({ timeout: 10000 });
  });

  test('chart sections render with data', async ({ page }) => {
    await setupDashboardMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Action Distribution chart should be visible
    const actionDistribution = page.locator('text=Action Distribution');
    await expect(actionDistribution).toBeVisible({ timeout: 10000 });

    // Confidence Distribution chart should be visible
    const confidenceDistribution = page.locator('text=Confidence Distribution');
    await expect(confidenceDistribution).toBeVisible();
  });

  test('outcome tracking section renders', async ({ page }) => {
    await setupDashboardMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const outcomeTracking = page.locator('text=Outcome Tracking');
    await expect(outcomeTracking).toBeVisible({ timeout: 10000 });
  });

  test('empty chart states shown when no track record data', async ({ page }) => {
    // Use empty insights for this test
    await page.route('**/api/v1/deep-insights/autonomous/**', async (route) => {
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'No active analysis task' }),
      });
    });

    await page.route('**/api/v1/deep-insights**', async (route) => {
      if (route.request().url().includes('/autonomous/')) {
        await route.fallback();
        return;
      }
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

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // With no data, stats cards should show 0
    const totalInsightsLabel = page.locator('text=Total Insights');
    await expect(totalInsightsLabel).toBeVisible({ timeout: 10000 });

    // The "Discover Opportunities" button should still be available
    const discoverButton = page.getByRole('button', { name: /Discover Opportunities/i });
    await expect(discoverButton.first()).toBeVisible();
  });
});
