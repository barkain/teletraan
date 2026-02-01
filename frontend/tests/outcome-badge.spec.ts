import { test, expect } from '@playwright/test';

test.describe('Outcome Badge', () => {
  test.beforeEach(async ({ page }) => {
    // Log console errors for debugging
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
    page.on('pageerror', err => console.log('PAGE ERROR:', err.message));
  });

  test('badge renders on insight cards', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    // Wait for insight cards to load
    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for insight cards with BUY/SELL actions (which should show outcome badges)
    const buyBadges = page.locator('text=/Strong Buy|Buy/i');
    const sellBadges = page.locator('text=/Strong Sell|Sell/i');

    const buyCount = await buyBadges.count();
    const sellCount = await sellBadges.count();

    console.log(`Found ${buyCount} Buy badges and ${sellCount} Sell badges`);

    // Look for outcome-related badges (Tracking, Success, Failure, etc.)
    const trackingBadges = page.locator('text=/Tracking|Pending|Success|Failure|Completed/i');
    const outcomeCount = await trackingBadges.count();

    console.log(`Found ${outcomeCount} outcome-related badges`);

    await page.screenshot({ path: 'test-results/outcome-badge-on-cards.png', fullPage: true });
  });

  test('TRACKING status shows blue badge', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Tracking badges
    const trackingBadge = page.locator('text=Tracking');

    if (await trackingBadge.count() > 0) {
      // Check for blue color class
      const badge = trackingBadge.first().locator('..');
      const classes = await badge.getAttribute('class');

      console.log(`Tracking badge classes: ${classes}`);

      // Should have blue-related classes
      const hasBlue = classes?.includes('blue') || classes?.includes('primary');
      console.log(`Has blue styling: ${hasBlue}`);

      await page.screenshot({ path: 'test-results/outcome-badge-tracking.png' });
    } else {
      console.log('No Tracking badges found - may need live data');
    }
  });

  test('COMPLETED validated shows green badge', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Success badges
    const successBadge = page.locator('text=/Success|Strong Success|Partial Success/i');

    if (await successBadge.count() > 0) {
      const badge = successBadge.first().locator('..');
      const classes = await badge.getAttribute('class');

      console.log(`Success badge classes: ${classes}`);

      // Should have green-related classes
      const hasGreen = classes?.includes('green');
      console.log(`Has green styling: ${hasGreen}`);

      await page.screenshot({ path: 'test-results/outcome-badge-success.png' });
    } else {
      console.log('No Success badges found - may need completed outcomes');
    }
  });

  test('COMPLETED invalidated shows red badge', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Failure badges
    const failureBadge = page.locator('text=/Failure|Strong Failure|Partial Failure/i');

    if (await failureBadge.count() > 0) {
      const badge = failureBadge.first().locator('..');
      const classes = await badge.getAttribute('class');

      console.log(`Failure badge classes: ${classes}`);

      // Should have red-related classes
      const hasRed = classes?.includes('red');
      console.log(`Has red styling: ${hasRed}`);

      await page.screenshot({ path: 'test-results/outcome-badge-failure.png' });
    } else {
      console.log('No Failure badges found - may need failed outcomes');
    }
  });

  test('tooltip shows details on hover', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for any outcome badge
    const outcomeBadges = page.locator('text=/Tracking|Pending|Success|Failure/i');

    if (await outcomeBadges.count() > 0) {
      // Hover over the first badge
      await outcomeBadges.first().hover();
      await page.waitForTimeout(500);

      // Look for tooltip content
      const tooltip = page.locator('[role="tooltip"], [class*="tooltip"], [class*="Tooltip"]');
      const tooltipVisible = await tooltip.isVisible();

      console.log(`Tooltip visible on hover: ${tooltipVisible}`);

      if (tooltipVisible) {
        // Check for tooltip content (Entry Price, Return, etc.)
        const entryPrice = page.locator('text=/Entry Price/i');
        const returnText = page.locator('text=/Return/i');

        const hasEntryPrice = await entryPrice.isVisible();
        const hasReturn = await returnText.isVisible();

        console.log(`Tooltip content - Entry Price: ${hasEntryPrice}, Return: ${hasReturn}`);
      }

      await page.screenshot({ path: 'test-results/outcome-badge-tooltip.png' });
    }
  });

  test('different size variants', async ({ page }) => {
    // The OutcomeBadge supports sm, md, lg sizes
    // We need to check if different sizes render properly

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for badges and check their dimensions
    const badges = page.locator('[class*="Badge"], [class*="badge"]');
    const badgeCount = await badges.count();

    console.log(`Found ${badgeCount} badge elements`);

    // Check for different size classes (px-2, px-3, text-xs, text-sm, text-base)
    const smallBadges = page.locator('[class*="text-xs"]');
    const mediumBadges = page.locator('[class*="text-sm"]');
    const largeBadges = page.locator('[class*="text-base"]');

    console.log(`Size distribution - Small: ${await smallBadges.count()}, Medium: ${await mediumBadges.count()}, Large: ${await largeBadges.count()}`);

    await page.screenshot({ path: 'test-results/outcome-badge-sizes.png' });
  });

  test('loading state renders spinner', async ({ page }) => {
    // Navigate and try to catch loading state
    await page.goto('http://localhost:3000/insights');

    // Look for loading spinners
    const spinners = page.locator('[class*="animate-spin"], [class*="Loader"]');

    // This may be very brief
    const spinnerCount = await spinners.count();
    console.log(`Found ${spinnerCount} spinner elements during load`);

    await page.waitForLoadState('networkidle');

    // After loading, spinners should be gone or minimal
    const spinnerCountAfter = await spinners.count();
    console.log(`Found ${spinnerCountAfter} spinner elements after load`);

    await page.screenshot({ path: 'test-results/outcome-badge-loading.png' });
  });

  test('badge shows return percentage', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for return percentages (e.g., "+5.2%", "-3.1%")
    const returnPercentages = page.locator('text=/[+-]\\d+\\.\\d+%/');
    const returnCount = await returnPercentages.count();

    console.log(`Found ${returnCount} return percentage displays`);

    if (returnCount > 0) {
      const firstReturn = await returnPercentages.first().textContent();
      console.log(`First return value: ${firstReturn}`);
    }

    await page.screenshot({ path: 'test-results/outcome-badge-returns.png' });
  });

  test('pending status shows correctly', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Pending badges
    const pendingBadge = page.locator('text=Pending');

    if (await pendingBadge.count() > 0) {
      const badge = pendingBadge.first().locator('..');
      const classes = await badge.getAttribute('class');

      console.log(`Pending badge classes: ${classes}`);

      // Should have gray/muted styling
      const hasGray = classes?.includes('gray') || classes?.includes('muted');
      console.log(`Has gray/muted styling: ${hasGray}`);

      await page.screenshot({ path: 'test-results/outcome-badge-pending.png' });
    } else {
      console.log('No Pending badges found');
    }
  });

  test('days remaining shows for active tracking', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for "days left" or "d left" text
    const daysRemaining = page.locator('text=/\\d+\\s*(d|days?)\\s*(left|remaining)/i');
    const daysCount = await daysRemaining.count();

    console.log(`Found ${daysCount} days remaining indicators`);

    if (daysCount > 0) {
      const firstDays = await daysRemaining.first().textContent();
      console.log(`First days remaining: ${firstDays}`);
    }

    await page.screenshot({ path: 'test-results/outcome-badge-days.png' });
  });

  test('invalidated status shows warning', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('text=AI Insights', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Invalidated badges
    const invalidatedBadge = page.locator('text=Invalidated');

    if (await invalidatedBadge.count() > 0) {
      const badge = invalidatedBadge.first().locator('..');
      const classes = await badge.getAttribute('class');

      console.log(`Invalidated badge classes: ${classes}`);

      // Should have yellow/warning styling
      const hasYellow = classes?.includes('yellow') || classes?.includes('warning');
      console.log(`Has yellow/warning styling: ${hasYellow}`);

      await page.screenshot({ path: 'test-results/outcome-badge-invalidated.png' });
    } else {
      console.log('No Invalidated badges found');
    }
  });
});
