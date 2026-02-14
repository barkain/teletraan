import { test } from './fixtures';

test.describe('App Debug', () => {
  test.beforeEach(async ({ page }) => {
    // Log console messages and page errors
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

  test('Dashboard loads', async ({ page }) => {
    const response = await page.goto('http://localhost:3000');
    console.log('Dashboard status:', response?.status());
    await page.waitForLoadState('domcontentloaded');

    // Take screenshot
    await page.screenshot({ path: 'test-results/dashboard.png', fullPage: true });

    // Check for error text
    const errorTexts = await page.locator('text=/error|Error|404|500/i').allTextContents();
    if (errorTexts.length > 0) {
      console.log('Dashboard error texts found:', errorTexts);
    }

    // Check page title or main content
    const title = await page.title();
    console.log('Dashboard title:', title);

    // Check for main content
    const bodyText = await page.locator('body').textContent();
    console.log('Dashboard body preview:', bodyText?.substring(0, 500));
  });

  test('Settings page loads', async ({ page }) => {
    const response = await page.goto('http://localhost:3000/settings');
    console.log('Settings status:', response?.status());
    await page.waitForLoadState('domcontentloaded');
    await page.screenshot({ path: 'test-results/settings.png', fullPage: true });

    const bodyText = await page.locator('body').textContent();
    console.log('Settings body preview:', bodyText?.substring(0, 500));

    // Check for form elements
    const inputs = await page.locator('input').count();
    const buttons = await page.locator('button').count();
    console.log('Settings inputs:', inputs, 'buttons:', buttons);
  });

  test('Insights page loads', async ({ page }) => {
    const response = await page.goto('http://localhost:3000/insights');
    console.log('Insights status:', response?.status());
    await page.waitForLoadState('domcontentloaded');
    await page.screenshot({ path: 'test-results/insights.png', fullPage: true });

    const bodyText = await page.locator('body').textContent();
    console.log('Insights body preview:', bodyText?.substring(0, 500));
  });

  test('Sectors page loads', async ({ page }) => {
    const response = await page.goto('http://localhost:3000/sectors');
    console.log('Sectors status:', response?.status());
    await page.waitForLoadState('domcontentloaded');
    await page.screenshot({ path: 'test-results/sectors.png', fullPage: true });

    const bodyText = await page.locator('body').textContent();
    console.log('Sectors body preview:', bodyText?.substring(0, 500));
  });

  test('Chat page loads', async ({ page }) => {
    const response = await page.goto('http://localhost:3000/chat');
    console.log('Chat status:', response?.status());
    await page.waitForLoadState('domcontentloaded');
    await page.screenshot({ path: 'test-results/chat.png', fullPage: true });

    const bodyText = await page.locator('body').textContent();
    console.log('Chat body preview:', bodyText?.substring(0, 500));
  });

  test('Stocks page loads', async ({ page }) => {
    const response = await page.goto('http://localhost:3000/stocks');
    console.log('Stocks status:', response?.status());
    await page.waitForLoadState('domcontentloaded');
    await page.screenshot({ path: 'test-results/stocks.png', fullPage: true });

    const bodyText = await page.locator('body').textContent();
    console.log('Stocks body preview:', bodyText?.substring(0, 500));
  });
});
