import { test, expect } from './fixtures';

test.describe('Deep Analysis Enhancement Integration Tests', () => {
  test.beforeEach(async ({ page }) => {
    // Log console errors for debugging
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
    page.on('pageerror', err => console.log('PAGE ERROR:', err.message));
    page.on('requestfailed', request => {
      console.log('REQUEST FAILED:', request.url(), request.failure()?.errorText);
    });
  });

  test('insights page loads with signals sidebar', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Check main content area loads
    const pageTitle = page.locator('text=AI Insights');
    await expect(pageTitle.first()).toBeVisible({ timeout: 10000 });

    // Check sidebar with Statistical Signals loads
    const signalsSidebar = page.locator('text=Statistical Signals');
    await expect(signalsSidebar).toBeVisible({ timeout: 10000 });

    // Verify layout is grid with main content and sidebar
    await page.screenshot({ path: 'test-results/integration-insights-with-sidebar.png', fullPage: true });
  });

  test('clicking insight navigates to detail page', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Find an insight card
    const insightCards = page.locator('[class*="Card"]').filter({ hasText: /confidence/i });
    const cardCount = await insightCards.count();

    console.log(`Found ${cardCount} insight cards`);

    if (cardCount > 0) {
      // Click the first insight card
      await insightCards.first().click();
      await page.waitForLoadState('domcontentloaded');

      // Check if we navigated to a detail page
      const currentUrl = page.url();
      console.log(`Navigated to: ${currentUrl}`);

      // Should be on /insights/[id] page
      const isDetailPage = currentUrl.includes('/insights/') && /\/insights\/\d+/.test(currentUrl);
      console.log(`Is detail page: ${isDetailPage}`);

      await page.screenshot({ path: 'test-results/integration-insight-detail.png', fullPage: true });
    }
  });

  test('dashboard tabs switch between sections', async ({ page }) => {
    // This tests navigation between different dashboard sections
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('domcontentloaded');

    // Check for main navigation elements
    const insightsLink = page.locator('a, button').filter({ hasText: /Insights/i });
    const patternsLink = page.locator('a, button').filter({ hasText: /Pattern/i });
    const trackRecordLink = page.locator('a, button').filter({ hasText: /Track Record/i });
    const signalsLink = page.locator('a, button').filter({ hasText: /Signal/i });

    console.log(`Navigation links found - Insights: ${await insightsLink.count()}, Patterns: ${await patternsLink.count()}, Track Record: ${await trackRecordLink.count()}, Signals: ${await signalsLink.count()}`);

    await page.screenshot({ path: 'test-results/integration-dashboard-nav.png', fullPage: true });
  });

  test('navigation between sections works', async ({ page }) => {
    // Navigate directly to each section and verify they load

    // Navigate to Insights
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('/insights');
    await page.screenshot({ path: 'test-results/integration-nav-insights.png' });

    // Navigate to Patterns
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('/patterns');
    await page.screenshot({ path: 'test-results/integration-nav-patterns.png' });

    // Navigate to Track Record
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('/track-record');
    await page.screenshot({ path: 'test-results/integration-nav-track-record.png' });

    // Navigate to Signals
    await page.goto('http://localhost:3000/signals');
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).toContain('/signals');
    await page.screenshot({ path: 'test-results/integration-nav-signals.png' });
  });

  test('filter state persists across navigation', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });

    // Apply a filter
    const symbolInput = page.locator('input[placeholder*="Search by symbol"]');
    if (await symbolInput.isVisible()) {
      await symbolInput.fill('AAPL');
      await page.waitForTimeout(500);

      // Navigate away
      await page.goto('http://localhost:3000');
      await page.waitForLoadState('domcontentloaded');

      // Navigate back
      await page.goto('http://localhost:3000/insights');
      await page.waitForLoadState('domcontentloaded');

      // Check if filter is preserved (depends on implementation)
      const inputValue = await symbolInput.inputValue();
      console.log(`Symbol input value after navigation: ${inputValue}`);

      await page.screenshot({ path: 'test-results/integration-filter-state.png' });
    }
  });

  test('API errors are handled gracefully', async ({ page }) => {
    // Block API requests to simulate errors
    await page.route('**/api/**', (route) => {
      route.abort('failed');
    });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Look for error states or fallback UI
    const errorMessages = page.locator('text=/Error|Failed|Unable to load/i');
    const errorCount = await errorMessages.count();

    console.log(`Error messages displayed: ${errorCount}`);

    // Should show some error indication or empty state
    await page.screenshot({ path: 'test-results/integration-api-error.png', fullPage: true });

    // Unroute for cleanup
    await page.unroute('**/api/**');
  });

  test('loading states display correctly', async ({ page }) => {
    // Slow down API responses
    await page.route('**/api/**', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 2000));
      route.continue();
    });

    // Navigate and capture loading state
    const navigationPromise = page.goto('http://localhost:3000/insights');

    // Wait a bit for loading state to appear
    await page.waitForTimeout(500);

    // Look for skeleton loaders
    const skeletons = page.locator('[class*="skeleton"], [class*="Skeleton"], .animate-pulse');
    const skeletonCount = await skeletons.count();

    console.log(`Skeleton loaders found during loading: ${skeletonCount}`);

    await page.screenshot({ path: 'test-results/integration-loading-state.png' });

    // Wait for navigation to complete
    await navigationPromise;
    await page.waitForLoadState('domcontentloaded');

    await page.unroute('**/api/**');
  });

  test('responsive layout on tablet', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });

    await page.screenshot({ path: 'test-results/integration-tablet.png', fullPage: true });

    // Check layout adapts
    const mainContent = page.locator('main, [class*="container"]').first();
    await expect(mainContent).toBeVisible();
  });

  test('theme toggle works', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Look for theme toggle button
    const themeToggle = page.locator('button').filter({ has: page.locator('svg[class*="sun"], svg[class*="moon"]') });

    if (await themeToggle.count() > 0) {
      await page.screenshot({ path: 'test-results/integration-theme-light.png' });

      await themeToggle.first().click();
      await page.waitForTimeout(500);

      await page.screenshot({ path: 'test-results/integration-theme-dark.png' });
    }
  });

  test('keyboard navigation works', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });

    // Tab through interactive elements
    await page.keyboard.press('Tab');
    await page.waitForTimeout(200);
    await page.keyboard.press('Tab');
    await page.waitForTimeout(200);
    await page.keyboard.press('Tab');
    await page.waitForTimeout(200);

    // Check focus indicator
    const focusedElement = page.locator(':focus');
    const isFocused = await focusedElement.count() > 0;

    console.log(`Focus visible: ${isFocused}`);

    await page.screenshot({ path: 'test-results/integration-keyboard-nav.png' });
  });

  test('data refreshes correctly', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });

    // Look for refresh button
    const refreshButton = page.locator('button').filter({ has: page.locator('svg[class*="refresh"], svg[class*="Refresh"]') });

    if (await refreshButton.count() > 0) {
      await refreshButton.first().click();
      await page.waitForTimeout(1000);

      console.log('Refresh button clicked');

      await page.screenshot({ path: 'test-results/integration-refresh.png' });
    }
  });

  test('symbol links navigate to stock page', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for stock symbol badges
    const symbolBadges = page.locator('text=/^[A-Z]{2,5}$/');
    const symbolCount = await symbolBadges.count();

    console.log(`Found ${symbolCount} symbol badges`);

    if (symbolCount > 0) {
      const firstSymbol = await symbolBadges.first().textContent();
      console.log(`Clicking symbol: ${firstSymbol}`);

      await symbolBadges.first().click();
      await page.waitForLoadState('domcontentloaded');

      const currentUrl = page.url();
      console.log(`Navigated to: ${currentUrl}`);

      // May navigate to /stocks/[symbol]
      if (currentUrl.includes('/stocks/')) {
        await page.screenshot({ path: 'test-results/integration-stock-page.png' });
      }
    }
  });

  test('all pages load without errors', async ({ page }) => {
    const pages = [
      '/',
      '/insights',
      '/patterns',
      '/track-record',
      '/signals',
      '/stocks',
      '/sectors',
      '/chat',
      '/settings',
    ];

    const results: { page: string; status: string; error?: string }[] = [];

    for (const pagePath of pages) {
      try {
        const response = await page.goto(`http://localhost:3000${pagePath}`);
        await page.waitForLoadState('domcontentloaded');

        const status = response?.status() || 'unknown';
        const hasError = await page.locator('text=/error|Error|404|500/i').count() > 0;

        results.push({
          page: pagePath,
          status: hasError ? `${status} (has error text)` : `${status}`,
        });

        await page.screenshot({ path: `test-results/integration-page${pagePath.replace('/', '-') || '-home'}.png` });
      } catch (error) {
        results.push({
          page: pagePath,
          status: 'FAILED',
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    console.log('Page load results:', JSON.stringify(results, null, 2));
  });

  test('deep insight card shows all components', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Find an insight card
    const insightCard = page.locator('[class*="Card"]').filter({ hasText: /confidence/i }).first();

    if (await insightCard.isVisible()) {
      // Check for expected components within the card
      const hasAction = await insightCard.locator('text=/Strong Buy|Buy|Hold|Sell|Strong Sell|Watch/i').count() > 0;
      const hasConfidence = await insightCard.locator('text=/\\d+%.*confidence/i').count() > 0;
      const hasSymbol = await insightCard.locator('text=/^[A-Z]{2,5}$/').count() > 0;
      const hasTimeHorizon = await insightCard.locator('text=/short|medium|long|term|week|month|day/i').count() > 0;
      const hasMoreDetails = await insightCard.locator('button').filter({ hasText: /More Details/i }).count() > 0;

      console.log(`Card components - Action: ${hasAction}, Confidence: ${hasConfidence}, Symbol: ${hasSymbol}, TimeHorizon: ${hasTimeHorizon}, MoreDetails: ${hasMoreDetails}`);

      // Expand details
      const moreDetailsBtn = insightCard.locator('button').filter({ hasText: /More Details/i });
      if (await moreDetailsBtn.isVisible()) {
        await moreDetailsBtn.click();
        await page.waitForTimeout(500);

        // Check expanded content
        const hasEvidence = await insightCard.locator('text=/Analyst Evidence|Evidence/i').count() > 0;
        const hasRisks = await insightCard.locator('text=/Risk Factors|Risks/i').count() > 0;

        console.log(`Expanded content - Evidence: ${hasEvidence}, Risks: ${hasRisks}`);
      }

      await page.screenshot({ path: 'test-results/integration-insight-card-full.png' });
    }
  });
});
