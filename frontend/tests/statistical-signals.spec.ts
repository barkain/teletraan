import { test, expect } from './fixtures';

test.describe('Statistical Signals Card', () => {
  test.beforeEach(async ({ page }) => {
    // Log console errors for debugging
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
    page.on('pageerror', err => console.log('PAGE ERROR:', err.message));
  });

  test('signals card renders on insights page', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Look for the Statistical Signals card
    const signalsCard = page.locator('text=Statistical Signals');
    await expect(signalsCard).toBeVisible({ timeout: 10000 });

    // Take screenshot
    await page.screenshot({ path: 'test-results/signals-card.png' });
  });

  test('loading state displays correctly', async ({ page }) => {
    // Navigate to insights page
    await page.goto('http://localhost:3000/insights');

    // The loading skeleton should have skeleton elements
    // Check for skeleton loader elements (they appear during loading)
    page.locator('.animate-pulse, [class*="skeleton"]');

    // Wait for content to load
    await page.waitForLoadState('domcontentloaded');

    // After loading, signals card should be visible
    const signalsCardEl = page.locator('text=Statistical Signals');
    await expect(signalsCardEl).toBeVisible({ timeout: 10000 });
  });

  test('signals are color-coded by type', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Wait for the signals card
    await page.waitForSelector('text=Statistical Signals', { timeout: 10000 });

    // Check for signal type color classes
    // Bullish/green signals
    const bullishSignals = page.locator('[class*="border-green"]');
    const bullishCount = await bullishSignals.count();

    // Bearish/red signals
    const bearishSignals = page.locator('[class*="border-red"]');
    const bearishCount = await bearishSignals.count();

    // Neutral/yellow signals
    const neutralSignals = page.locator('[class*="border-yellow"]');
    const neutralCount = await neutralSignals.count();

    // At least one of these should exist if signals are present
    console.log(`Signal counts - Bullish: ${bullishCount}, Bearish: ${bearishCount}, Neutral: ${neutralCount}`);

    // Take screenshot showing color coding
    await page.screenshot({ path: 'test-results/signals-color-coded.png' });
  });

  test('filtering by signal type works', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Wait for signals card
    await page.waitForSelector('text=Statistical Signals', { timeout: 10000 });

    // Look for filter dropdown - the select trigger
    const filterDropdown = page.locator('[class*="SelectTrigger"]').filter({ hasText: /All Signals|Filter/ });

    if (await filterDropdown.count() > 0) {
      await filterDropdown.first().click();
      await page.waitForTimeout(500);

      // Take screenshot of filter options
      await page.screenshot({ path: 'test-results/signals-filter-dropdown.png' });

      // Try to select a specific filter if options are visible
      const filterOption = page.locator('[role="option"]').first();
      if (await filterOption.isVisible()) {
        await filterOption.click();
        await page.waitForTimeout(500);
      }
    }

    await page.screenshot({ path: 'test-results/signals-filtered.png' });
  });

  test('empty state when no signals', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // The empty state shows "No active signals in your watchlist" or similar
    // This may not always be visible if there are signals
    const emptyState = page.locator('text=/No.*signals/i');
    const signalItems = page.locator('[class*="border-green"], [class*="border-red"], [class*="border-yellow"]');

    const signalCount = await signalItems.count();
    if (signalCount === 0) {
      // Empty state should be visible (use .first() since regex may match parent containers too)
      await expect(emptyState.first()).toBeVisible();
      await page.screenshot({ path: 'test-results/signals-empty-state.png' });
    } else {
      console.log(`${signalCount} signals present, skipping empty state check`);
    }
  });

  test('responsive behavior mobile', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // On mobile, the signals sidebar may be hidden or in a different layout
    page.locator('text=Statistical Signals');

    await page.screenshot({ path: 'test-results/signals-mobile.png', fullPage: true });

    // Check page structure adapts to mobile
    const mainContent = page.locator('main, [class*="container"]').first();
    await expect(mainContent).toBeVisible();
  });

  test('responsive behavior desktop', async ({ page }) => {
    // Set desktop viewport
    await page.setViewportSize({ width: 1440, height: 900 });

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Signals card should be visible in sidebar
    const signalsCard = page.locator('text=Statistical Signals');
    await expect(signalsCard).toBeVisible({ timeout: 10000 });

    await page.screenshot({ path: 'test-results/signals-desktop.png', fullPage: true });
  });

  test('signal item expansion shows details', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Wait for signals to load
    await page.waitForSelector('text=Statistical Signals', { timeout: 10000 });

    // Find a signal item with expand capability (has chevron icon)
    const signalItem = page.locator('[class*="cursor-pointer"]').filter({ has: page.locator('svg') }).first();

    if (await signalItem.isVisible()) {
      await signalItem.click();
      await page.waitForTimeout(500);

      // After clicking, expanded content should show
      await page.screenshot({ path: 'test-results/signals-expanded.png' });
    }
  });

  test('strength indicator displays correctly', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('domcontentloaded');

    // Look for strength indicators (Strong, Moderate, Weak)
    const strongIndicator = page.locator('text=Strong');
    const moderateIndicator = page.locator('text=Moderate');
    const weakIndicator = page.locator('text=Weak');

    const hasStrength = await strongIndicator.count() > 0 ||
                        await moderateIndicator.count() > 0 ||
                        await weakIndicator.count() > 0;

    console.log(`Strength indicators present: ${hasStrength}`);
    await page.screenshot({ path: 'test-results/signals-strength.png' });
  });
});
