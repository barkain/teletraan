import { test, expect } from '@playwright/test';

test.describe('Teletraan UI Debug', () => {
  test.beforeEach(async ({ page }) => {
    // Capture console errors
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });

    // Capture page errors
    page.on('pageerror', err => {
      console.log('PAGE ERROR:', err.message);
    });
  });

  test('Dashboard page loads', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForTimeout(3000);

    // Take screenshot
    await page.screenshot({ path: 'debug-dashboard.png', fullPage: true });

    // Check for visible errors
    const errorElements = await page.locator('[class*="error"], [class*="Error"]').count();
    console.log('Error elements found:', errorElements);

    // Get page content for debugging
    const content = await page.content();
    console.log('Page title:', await page.title());
  });

  test('Stocks page loads', async ({ page }) => {
    await page.goto('http://localhost:3000/stocks');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'debug-stocks.png', fullPage: true });
  });

  test('Insights page loads', async ({ page }) => {
    await page.goto('http://localhost:3000/insights');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'debug-insights.png', fullPage: true });
  });

  test('Chat page loads', async ({ page }) => {
    await page.goto('http://localhost:3000/chat');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: 'debug-chat.png', fullPage: true });
  });
});
