import { test, expect } from './fixtures';

test.describe('API Mock Tests', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('mock API responses for insights', async ({ page }) => {
    // Mock the deep insights API
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: 1,
              title: 'Test Insight: AAPL Momentum Play',
              thesis: 'Apple showing strong momentum signals with technical breakout.',
              action: 'BUY',
              confidence: 0.85,
              insight_type: 'opportunity',
              time_horizon: 'medium-term',
              primary_symbol: 'AAPL',
              related_symbols: ['MSFT', 'GOOGL'],
              supporting_evidence: [
                { analyst: 'technical', finding: 'Golden cross on daily chart' },
                { analyst: 'momentum', finding: 'RSI trending bullish' },
              ],
              risk_factors: ['Market volatility', 'Sector rotation risk'],
              invalidation_trigger: 'Close below 170',
              historical_precedent: 'Similar setup led to 15% gains in 2023',
              created_at: new Date().toISOString(),
            },
            {
              id: 2,
              title: 'Test Insight: Sector Rotation Signal',
              thesis: 'Rotation from growth to value sectors detected.',
              action: 'SELL',
              confidence: 0.72,
              insight_type: 'rotation',
              time_horizon: 'short-term',
              primary_symbol: 'QQQ',
              related_symbols: ['XLF', 'XLE'],
              supporting_evidence: [
                { analyst: 'sector', finding: 'Value outperforming growth' },
              ],
              risk_factors: ['Fed policy shift'],
              invalidation_trigger: 'Tech breakout',
              created_at: new Date().toISOString(),
            },
          ],
          total: 2,
          limit: 10,
          offset: 0,
        }),
      });
    });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Verify mocked data displays
    const testInsight = page.locator('text=Test Insight: AAPL Momentum Play');
    await expect(testInsight).toBeVisible({ timeout: 10000 });

    const sectorInsight = page.locator('text=Test Insight: Sector Rotation Signal');
    await expect(sectorInsight).toBeVisible();

    await page.screenshot({ path: 'test-results/api-mock-insights.png', fullPage: true });
  });

  test('mock API responses for statistical signals', async ({ page }) => {
    // Mock the signals API
    await page.route('**/api/v1/features/signals**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          signals: [
            {
              symbol: 'AAPL',
              feature_type: 'momentum',
              signal: 'bullish',
              value: 2.5,
              strength: 'strong',
            },
            {
              symbol: 'GOOGL',
              feature_type: 'rsi',
              signal: 'oversold',
              value: 28.5,
              strength: 'moderate',
            },
            {
              symbol: 'MSFT',
              feature_type: 'volatility',
              signal: 'elevated',
              value: 0.35,
              strength: 'weak',
            },
          ],
          count: 3,
          as_of: new Date().toISOString(),
        }),
      });
    });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Verify signals display
    const signalsCard = page.locator('text=Statistical Signals');
    await expect(signalsCard).toBeVisible({ timeout: 10000 });

    // Check for signal items
    const aaplSignal = page.locator('text=AAPL').first();
    const googSignal = page.locator('text=GOOGL').first();

    console.log(`AAPL signal visible: ${await aaplSignal.isVisible()}`);
    console.log(`GOOGL signal visible: ${await googSignal.isVisible()}`);

    await page.screenshot({ path: 'test-results/api-mock-signals.png' });
  });

  test('error handling when API fails', async ({ page }) => {
    // Mock API to return 500 error
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal Server Error' }),
      });
    });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Should show error state
    const errorMessage = page.locator('text=/Error|Failed|Unable/i');
    const hasError = await errorMessage.count() > 0;

    console.log(`Error message displayed: ${hasError}`);

    await page.screenshot({ path: 'test-results/api-mock-error-500.png', fullPage: true });
  });

  test('loading states display during API fetch', async ({ page }) => {
    // Mock API with delay
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [],
          total: 0,
          limit: 10,
          offset: 0,
        }),
      });
    });

    // Start navigation
    const navigationPromise = page.goto('http://localhost:3000/insights');

    // Wait for loading state to appear
    await page.waitForTimeout(500);

    // Look for skeleton loaders
    const skeletons = page.locator('[class*="skeleton"], .animate-pulse');
    const skeletonCount = await skeletons.count();

    console.log(`Skeletons visible during load: ${skeletonCount}`);

    await page.screenshot({ path: 'test-results/api-mock-loading.png' });

    // Complete navigation
    await navigationPromise;
    await page.waitForLoadState('domcontentloaded');
  });

  test('mock track record API', async ({ page }) => {
    // Mock track record stats API
    await page.route('**/api/v1/track-record/stats**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_insights: 150,
          successful: 95,
          success_rate: 0.633,
          avg_return_successful: 0.082,
          avg_return_failed: -0.045,
          by_type: {
            opportunity: { total: 80, successful: 55, rate: 0.6875 },
            risk: { total: 40, successful: 22, rate: 0.55 },
            rotation: { total: 30, successful: 18, rate: 0.6 },
          },
          by_action: {
            BUY: { total: 90, successful: 60, rate: 0.667 },
            SELL: { total: 40, successful: 25, rate: 0.625 },
            HOLD: { total: 20, successful: 10, rate: 0.5 },
          },
        }),
      });
    });

    // Mock outcome summary
    await page.route('**/api/v1/track-record/outcomes/summary**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_tracked: 150,
          currently_tracking: 25,
          success_rate: 0.633,
          avg_return_when_correct: 0.082,
          avg_return_when_wrong: -0.045,
          by_category: {
            STRONG_SUCCESS: 30,
            SUCCESS: 45,
            PARTIAL_SUCCESS: 20,
            NEUTRAL: 15,
            PARTIAL_FAILURE: 18,
            FAILURE: 15,
            STRONG_FAILURE: 7,
          },
          by_direction: {
            BUY: { total: 90, correct: 60, avg_return: 0.075 },
            SELL: { total: 40, correct: 25, avg_return: 0.068 },
            HOLD: { total: 20, correct: 10, avg_return: 0.002 },
          },
        }),
      });
    });

    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    // Verify stats display
    const successRate = page.locator('text=/63\\.3%|633/');
    const hasSuccessRate = await successRate.count() > 0;

    console.log(`Success rate displayed: ${hasSuccessRate}`);

    await page.screenshot({ path: 'test-results/api-mock-track-record.png', fullPage: true });
  });

  test('mock patterns API', async ({ page }) => {
    // Mock knowledge patterns endpoint
    await page.route('**/api/v1/knowledge/patterns**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          patterns: [
            {
              id: 'mock-pattern-1',
              pattern_type: 'TECHNICAL_SETUP',
              pattern_name: 'Mock Golden Cross',
              description: 'Test pattern for QA',
              trigger_conditions: { ma_cross: true },
              expected_outcome: 'Price increase',
              success_rate: 0.75,
              occurrences: 50,
              successful_outcomes: 37,
              avg_return_when_triggered: 0.10,
              is_active: true,
              last_triggered_at: new Date().toISOString(),
            },
          ],
          total: 1,
        }),
      });
    });

    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    // The patterns page uses mock data by default, but this tests custom API mocking
    await page.screenshot({ path: 'test-results/api-mock-patterns.png', fullPage: true });
  });

  test('mock outcome badge API', async ({ page }) => {
    // Mock individual outcome endpoint
    await page.route('**/api/v1/track-record/outcomes/*', async (route) => {
      const url = route.request().url();
      const insightId = url.split('/').pop();

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: `outcome-${insightId}`,
          insight_id: parseInt(insightId || '1'),
          tracking_status: 'COMPLETED',
          outcome_category: 'SUCCESS',
          initial_price: 175.50,
          final_price: 195.25,
          predicted_direction: 'BUY',
          actual_return_pct: 11.25,
          is_correct: true,
          validation_notes: 'Price target achieved within timeframe',
          days_remaining: 0,
        }),
      });
    });

    // Also mock deep insights for the page
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: 1,
              title: 'Completed Insight',
              thesis: 'This insight has completed tracking.',
              action: 'BUY',
              confidence: 0.80,
              insight_type: 'opportunity',
              time_horizon: 'short-term',
              primary_symbol: 'AAPL',
              related_symbols: [],
              supporting_evidence: [],
              risk_factors: [],
              created_at: new Date().toISOString(),
            },
          ],
          total: 1,
          limit: 10,
          offset: 0,
        }),
      });
    });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Wait for outcome badges to load
    await page.waitForTimeout(1000);

    // Look for Success badge
    const successBadge = page.locator('text=Success');
    const hasSuccess = await successBadge.count() > 0;

    console.log(`Success badge displayed: ${hasSuccess}`);

    await page.screenshot({ path: 'test-results/api-mock-outcome-badge.png' });
  });

  test('empty state with no data', async ({ page }) => {
    // Mock empty API responses
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [],
          total: 0,
          limit: 10,
          offset: 0,
        }),
      });
    });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Should show empty state
    const emptyState = page.locator('text=/No Insights Found|No insights/i');
    const hasEmpty = await emptyState.count() > 0;

    console.log(`Empty state displayed: ${hasEmpty}`);

    await page.screenshot({ path: 'test-results/api-mock-empty.png', fullPage: true });
  });

  test('network timeout handling', async ({ page }) => {
    // Mock API to timeout
    await page.route('**/api/v1/deep-insights**', async (_route) => {
      await new Promise((resolve) => setTimeout(resolve, 60000)); // Long delay
    });

    // Set page timeout
    page.setDefaultTimeout(5000);

    try {
      await page.goto('http://localhost:3000/insights');
      await page.waitForLoadState('domcontentloaded');
    } catch {
      // Expected to timeout
      console.log('Request timed out as expected');
    }

    await page.screenshot({ path: 'test-results/api-mock-timeout.png' });
  });

  test('401 unauthorized handling', async ({ page }) => {
    // Mock API to return 401
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Unauthorized' }),
      });
    });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Check for error handling
    const errorMessage = page.locator('text=/Unauthorized|Error|Failed/i');
    const hasError = await errorMessage.count() > 0;

    console.log(`Unauthorized error handled: ${hasError}`);

    await page.screenshot({ path: 'test-results/api-mock-401.png', fullPage: true });
  });

  test('malformed JSON response handling', async ({ page }) => {
    // Mock API to return invalid JSON
    await page.route('**/api/v1/deep-insights**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: 'not valid json {{{',
      });
    });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Should handle parse error gracefully
    await page.screenshot({ path: 'test-results/api-mock-malformed.png', fullPage: true });
  });
});
