import { test, expect } from '@playwright/test';

test.describe('Debug Deep Insights', () => {
  test('Check dashboard AI Insights section', async ({ page }) => {
    // Listen to console and network
    page.on('console', msg => console.log('CONSOLE:', msg.type(), msg.text()));
    page.on('response', response => {
      if (response.url().includes('deep-insights')) {
        console.log('API Response:', response.url(), response.status());
      }
    });

    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Screenshot dashboard
    await page.screenshot({ path: 'test-results/dashboard.png', fullPage: true });

    // Check for AI Insights section
    const aiInsights = await page.locator('text=AI Insights').count();
    console.log('AI Insights sections found:', aiInsights);

    // Check for insight cards
    const insightCards = await page.locator('[class*="insight"]').count();
    console.log('Insight cards found:', insightCards);

    // Check for any error messages
    const errors = await page.locator('text=error').count();
    console.log('Errors on page:', errors);
  });

  test('Check Insights page', async ({ page }) => {
    page.on('console', msg => console.log('CONSOLE:', msg.type(), msg.text()));
    page.on('requestfailed', request => console.log('FAILED:', request.url()));

    await page.goto('http://localhost:3000/insights');
    await page.waitForLoadState('networkidle');

    await page.screenshot({ path: 'test-results/insights-page.png', fullPage: true });

    // Check content
    const content = await page.textContent('body');
    console.log('Page contains deep insight cards:', content?.includes('DeepInsight') || content?.includes('confidence'));
  });
});
