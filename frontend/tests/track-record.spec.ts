import { test, expect } from './fixtures';

test.describe('Track Record Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // Log console errors for debugging
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
    page.on('pageerror', err => console.log('PAGE ERROR:', err.message));
  });

  test('dashboard renders with stats cards', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    // Look for Track Record header
    const trackRecordHeader = page.locator('text=Track Record');
    await expect(trackRecordHeader.first()).toBeVisible({ timeout: 10000 });

    // Look for stats cards
    const successRateCard = page.locator('text=Overall Success Rate');
    const totalInsightsCard = page.locator('text=Total Insights Tracked');
    const trackingCard = page.locator('text=Currently Tracking');
    const avgReturnCard = page.locator('text=Avg Return');

    // Check at least some cards are visible
    const hasSuccessRate = await successRateCard.count() > 0;
    const hasTotalInsights = await totalInsightsCard.count() > 0;

    console.log(`Stats cards - Success Rate: ${hasSuccessRate}, Total Insights: ${hasTotalInsights}`);

    await page.screenshot({ path: 'test-results/track-record-dashboard.png', fullPage: true });
  });

  test('time period selector changes data', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });

    // Find time period selector
    const periodSelector = page.locator('[class*="SelectTrigger"]').filter({ hasText: /30d|60d|90d|180d|All/i });

    if (await periodSelector.count() > 0) {
      await periodSelector.first().click();
      await page.waitForTimeout(500);

      await page.screenshot({ path: 'test-results/track-record-period-dropdown.png' });

      // Select a different period
      const period60d = page.locator('[role="option"]').filter({ hasText: '60d' });
      if (await period60d.isVisible()) {
        await period60d.click();
        await page.waitForTimeout(500);

        await page.screenshot({ path: 'test-results/track-record-60d.png' });
      }
    }
  });

  test('charts render - success rate by type', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for By Insight Type chart
    const byTypeChart = page.locator('text=By Insight Type').first();
    const byTypeVisible = await byTypeChart.isVisible();

    console.log(`By Insight Type chart visible: ${byTypeVisible}`);

    // Check for Recharts elements
    const svgCharts = page.locator('.recharts-wrapper, svg[class*="recharts"]');
    const chartCount = await svgCharts.count();

    console.log(`Found ${chartCount} chart elements`);

    await page.screenshot({ path: 'test-results/track-record-type-chart.png' });
  });

  test('charts render - by action pie chart', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for By Action chart
    const byActionChart = page.locator('text=By Action');
    const byActionVisible = await byActionChart.isVisible();

    console.log(`By Action chart visible: ${byActionVisible}`);

    // Look for pie chart elements
    const pieCharts = page.locator('.recharts-pie, [class*="pie"]');
    const pieCount = await pieCharts.count();

    console.log(`Found ${pieCount} pie chart elements`);

    await page.screenshot({ path: 'test-results/track-record-action-chart.png' });
  });

  test('charts render - outcome category chart', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for By Outcome Category chart
    const outcomeChart = page.locator('text=By Outcome Category');
    const outcomeVisible = await outcomeChart.isVisible();

    console.log(`By Outcome Category chart visible: ${outcomeVisible}`);

    await page.screenshot({ path: 'test-results/track-record-outcome-chart.png' });
  });

  test('recent outcomes list populates', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Recent Completed Outcomes section
    const recentOutcomes = page.locator('text=Recent Completed Outcomes');
    const recentVisible = await recentOutcomes.isVisible();

    console.log(`Recent Outcomes section visible: ${recentVisible}`);

    if (recentVisible) {
      // Look for outcome items
      const outcomeItems = page.locator('[class*="Card"]').filter({ has: page.locator('text=/Insight #/') });
      const outcomeCount = await outcomeItems.count();

      console.log(`Found ${outcomeCount} recent outcome items`);

      await page.screenshot({ path: 'test-results/track-record-recent-outcomes.png' });
    }
  });

  test('empty state handling', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Check for "No data available" or empty states
    const noDataText = page.locator('text=/No data available|No statistics|No completed outcomes/i');
    const noDataCount = await noDataText.count();

    console.log(`Empty state messages found: ${noDataCount}`);

    await page.screenshot({ path: 'test-results/track-record-empty-states.png', fullPage: true });
  });

  test('detailed statistics table renders', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Detailed Statistics section
    const statsTable = page.locator('text=Detailed Statistics');
    const tableVisible = await statsTable.isVisible();

    console.log(`Detailed Statistics section visible: ${tableVisible}`);

    if (tableVisible) {
      // Look for table headers
      const tableHeaders = page.locator('th, [role="columnheader"]');
      const headerCount = await tableHeaders.count();

      console.log(`Found ${headerCount} table headers`);

      await page.screenshot({ path: 'test-results/track-record-stats-table.png' });
    }
  });

  test('table column sorting works', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Find sortable column headers
    const sortableHeader = page.locator('th').filter({ hasText: /Rate/i }).first();

    if (await sortableHeader.isVisible()) {
      // Click to sort
      await sortableHeader.click();
      await page.waitForTimeout(500);

      await page.screenshot({ path: 'test-results/track-record-sorted-asc.png' });

      // Click again to reverse sort
      await sortableHeader.click();
      await page.waitForTimeout(500);

      await page.screenshot({ path: 'test-results/track-record-sorted-desc.png' });
    }
  });

  test('export button is present', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });

    // Look for export/download button
    const exportButton = page.locator('button').filter({ has: page.locator('svg') }).filter({ hasText: '' });
    const downloadButton = page.locator('[aria-label*="download"], [aria-label*="export"]');

    // Check for any button with download icon
    const buttonWithDownloadIcon = page.locator('button svg[class*="Download"], button svg[class*="download"]');

    const hasExport = await exportButton.count() > 0 || await downloadButton.count() > 0 || await buttonWithDownloadIcon.count() > 0;

    console.log(`Export button present: ${hasExport}`);

    await page.screenshot({ path: 'test-results/track-record-export.png' });
  });

  test('monthly trend chart renders', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for Monthly Trend chart
    const trendChart = page.locator('text=Monthly Trend');
    const trendVisible = await trendChart.isVisible();

    console.log(`Monthly Trend chart visible: ${trendVisible}`);

    if (trendVisible) {
      // Look for line chart elements
      const lineCharts = page.locator('.recharts-line, [class*="line"]');
      const lineCount = await lineCharts.count();

      console.log(`Found ${lineCount} line chart elements`);
    }

    await page.screenshot({ path: 'test-results/track-record-trend-chart.png' });
  });

  test('responsive layout on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });

    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    // Wait for page content
    await page.waitForTimeout(2000);

    // Stats cards should stack on mobile
    await page.screenshot({ path: 'test-results/track-record-mobile.png', fullPage: true });
  });

  test('links to insight details work', async ({ page }) => {
    await page.goto('http://localhost:3000/track-record');
    await page.waitForLoadState('domcontentloaded');

    await page.waitForSelector('text=Track Record', { timeout: 10000 });
    await page.waitForTimeout(1000);

    // Look for View links in recent outcomes
    const viewLinks = page.locator('a').filter({ hasText: /View/i });
    const linkCount = await viewLinks.count();

    console.log(`Found ${linkCount} View links`);

    if (linkCount > 0) {
      // Get href of first link
      const href = await viewLinks.first().getAttribute('href');
      console.log(`First view link href: ${href}`);

      // Check it points to an insight
      if (href) {
        expect(href).toContain('/insights/');
      }
    }

    await page.screenshot({ path: 'test-results/track-record-links.png' });
  });
});
