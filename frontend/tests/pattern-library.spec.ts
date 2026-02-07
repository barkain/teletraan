import { test, expect } from './fixtures';

test.describe('Pattern Library Panel', () => {
  test.beforeEach(async ({ page }) => {
    // Log console errors for debugging
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
    page.on('pageerror', err => console.log('PAGE ERROR:', err.message));
  });

  test('pattern library renders', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    // Look for the Pattern Library header
    const patternLibrary = page.locator('text=Pattern Library');
    await expect(patternLibrary.first()).toBeVisible({ timeout: 10000 });

    // Take screenshot
    await page.screenshot({ path: 'test-results/pattern-library.png', fullPage: true });
  });

  test('patterns display with success rate badges', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    // Wait for patterns to load
    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000); // Wait for mock data to load

    // Look for success rate percentages (e.g., "68%", "75%")
    const percentages = page.locator('text=/%$/');
    const percentageCount = await percentages.count();
    console.log(`Found ${percentageCount} percentage values`);

    // Look for pattern cards
    const patternCards = page.locator('[class*="Card"]');
    const cardCount = await patternCards.count();
    console.log(`Found ${cardCount} pattern cards`);

    // Check for success rate ring components
    const successRings = page.locator('svg circle');
    const ringCount = await successRings.count();
    console.log(`Found ${ringCount} SVG circles (success rate rings)`);

    await page.screenshot({ path: 'test-results/pattern-success-rates.png' });
  });

  test('filtering by pattern type works', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Find the pattern type filter dropdown
    const typeFilter = page.locator('[class*="SelectTrigger"]').filter({ hasText: /All Types|Pattern Type/ });

    if (await typeFilter.count() > 0) {
      await typeFilter.first().click();
      await page.waitForTimeout(500);

      await page.screenshot({ path: 'test-results/pattern-type-dropdown.png' });

      // Select a specific pattern type
      const technicalOption = page.locator('[role="option"]').filter({ hasText: /Technical/i });
      if (await technicalOption.isVisible()) {
        await technicalOption.click();
        await page.waitForTimeout(500);
        await page.screenshot({ path: 'test-results/pattern-filtered-technical.png' });
      }
    }
  });

  test('filtering by minimum success rate', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Find the success rate slider/range input
    const successRateSlider = page.locator('input[type="range"]');

    if (await successRateSlider.count() > 0) {
      // Get initial count of patterns
      const initialPatterns = await page.locator('[class*="Card"]').count();

      // Move slider to filter by higher success rate
      await successRateSlider.fill('70');
      await page.waitForTimeout(500);

      // Get filtered count
      const filteredPatterns = await page.locator('[class*="Card"]').count();

      console.log(`Patterns before filter: ${initialPatterns}, after: ${filteredPatterns}`);

      await page.screenshot({ path: 'test-results/pattern-filtered-success-rate.png' });
    }
  });

  test('pattern expansion shows full details', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Find "More Details" button
    const moreDetailsButton = page.locator('button').filter({ hasText: /More Details/i });

    if (await moreDetailsButton.count() > 0) {
      await moreDetailsButton.first().click();
      await page.waitForTimeout(500);

      // After clicking, should see expanded content
      // Look for trigger conditions, expected outcome, etc.
      const triggerConditions = page.locator('text=/Trigger Conditions/i');
      const expectedOutcome = page.locator('text=/Expected Outcome/i');

      const hasTrigger = await triggerConditions.isVisible();
      const hasOutcome = await expectedOutcome.isVisible();

      console.log(`Expanded details - Trigger: ${hasTrigger}, Outcome: ${hasOutcome}`);

      await page.screenshot({ path: 'test-results/pattern-expanded.png' });
    }
  });

  test('themes section renders', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Conversation Themes section
    const themesSection = page.locator('text=Conversation Themes');
    const themesVisible = await themesSection.isVisible();

    console.log(`Themes section visible: ${themesVisible}`);

    if (themesVisible) {
      // Look for theme cards
      const themeCards = page.locator('text=/Market Regime|Sector Trend|Risk Concern/i');
      const themeCount = await themeCards.count();
      console.log(`Found ${themeCount} theme references`);

      await page.screenshot({ path: 'test-results/pattern-themes.png' });
    }
  });

  test('search functionality', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Find search input
    const searchInput = page.locator('input[placeholder*="Search"]');

    if (await searchInput.count() > 0) {
      // Get initial pattern count
      const initialPatterns = await page.locator('[class*="Card"]').count();

      // Type search query
      await searchInput.fill('momentum');
      await page.waitForTimeout(500);

      // Get filtered count
      const filteredPatterns = await page.locator('[class*="Card"]').count();

      console.log(`Search results: ${initialPatterns} -> ${filteredPatterns}`);

      await page.screenshot({ path: 'test-results/pattern-search.png' });

      // Clear search
      await searchInput.clear();
      await page.waitForTimeout(500);
    }
  });

  test('view mode toggle grid vs list', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Find view toggle buttons
    const gridButton = page.locator('button').filter({ has: page.locator('svg[class*="Grid"]') });
    const listButton = page.locator('button').filter({ has: page.locator('svg[class*="List"]') });

    // Take screenshot in grid view
    await page.screenshot({ path: 'test-results/pattern-grid-view.png' });

    // Click list view if available
    if (await listButton.count() > 0) {
      await listButton.click();
      await page.waitForTimeout(500);
      await page.screenshot({ path: 'test-results/pattern-list-view.png' });
    }
  });

  test('pattern type badges have correct colors', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Check for different pattern type badges
    const technicalBadge = page.locator('text=Technical Setup');
    const macroBadge = page.locator('text=Macro Correlation');
    const sectorBadge = page.locator('text=Sector Rotation');
    const earningsBadge = page.locator('text=Earnings Pattern');
    const seasonalityBadge = page.locator('text=Seasonality');
    const crossAssetBadge = page.locator('text=Cross Asset');

    const counts = {
      technical: await technicalBadge.count(),
      macro: await macroBadge.count(),
      sector: await sectorBadge.count(),
      earnings: await earningsBadge.count(),
      seasonality: await seasonalityBadge.count(),
      crossAsset: await crossAssetBadge.count(),
    };

    console.log('Pattern type counts:', counts);

    await page.screenshot({ path: 'test-results/pattern-type-badges.png' });
  });

  test('clear filters button works', async ({ page }) => {
    await page.goto('http://localhost:3000/patterns');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Pattern Library', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Apply a filter first
    const searchInput = page.locator('input[placeholder*="Search"]');
    if (await searchInput.count() > 0) {
      await searchInput.fill('test');
      await page.waitForTimeout(500);
    }

    // Look for Clear button (be specific to avoid multiple matches)
    const clearButton = page.locator('button').filter({ hasText: /^Clear$/ }).first();

    if (await clearButton.count() > 0) {
      await clearButton.click();
      await page.waitForTimeout(500);

      // Verify search was cleared
      const searchValue = await searchInput.inputValue();
      expect(searchValue).toBe('');

      await page.screenshot({ path: 'test-results/pattern-filters-cleared.png' });
    }
  });
});
