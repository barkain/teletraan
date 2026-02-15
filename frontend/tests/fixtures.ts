/* eslint-disable react-hooks/rules-of-hooks */
import { test as base } from '@playwright/test';

export const test = base.extend({
  page: async ({ page }, use) => {
    // Catch-all for any unhandled API requests - return empty/default responses
    // Register specific routes BEFORE broad patterns so they take priority

    await page.route('**/api/v1/deep-insights/autonomous/active', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(null) })
    );
    await page.route('**/api/v1/deep-insights/autonomous/**', route =>
      route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'No active analysis task' }),
      })
    );
    await page.route('**/api/v1/deep-insights**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      })
    );
    await page.route('**/api/v1/features/signals**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ signals: [], count: 0, as_of: new Date().toISOString() }),
      })
    );
    await page.route('**/api/v1/track-record/**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      })
    );
    await page.route('**/api/v1/outcomes/**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_tracked: 0,
          completed: 0,
          currently_tracking: 0,
          success_rate: null,
          avg_return_when_correct: null,
          by_direction: {},
        }),
      })
    );
    await page.route('**/api/v1/knowledge/patterns/summary', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ total: 0, active: 0, top_symbols: [], top_sectors: [], by_type: {} }),
      })
    );
    await page.route('**/api/v1/knowledge/track-record/monthly-trend', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: [] }),
      })
    );
    await page.route('**/api/v1/knowledge/track-record', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ by_action: {}, by_type: {} }),
      })
    );
    await page.route('**/api/v1/knowledge/**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ patterns: [], themes: [], total: 0 }),
      })
    );
    await page.route('**/api/v1/conversations**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      })
    );
    await page.route('**/api/v1/settings**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      })
    );
    await page.route('**/api/v1/stocks**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      })
    );
    await page.route('**/api/v1/insights**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      })
    );
    await page.route('**/api/v1/health**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'healthy', version: '1.0.0' }),
      })
    );
    // Catch-all for any remaining /api/v1/ requests
    await page.route('**/api/v1/**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      })
    );
    // Catch-all for /api/market/ requests
    await page.route('**/api/market/**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({}),
      })
    );

    await use(page);
  },
});

export { expect } from '@playwright/test';
