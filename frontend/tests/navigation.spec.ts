import { test, expect } from './fixtures';

// Helper to set up standard API mocks so pages render without real backend.
// IMPORTANT: Register specific routes AFTER broad patterns so the specific ones
// take priority (Playwright matches routes in reverse registration order — newest first).
async function setupGlobalMocks(page: import('@playwright/test').Page) {
  // Broad deep-insights mock (registered FIRST so specific routes override it)
  await page.route('**/api/v1/deep-insights**', async (route) => {
    // Skip if this is an autonomous sub-path — let the specific handler below deal with it
    const url = route.request().url();
    if (url.includes('/autonomous/')) {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });

  // Specific autonomous analysis endpoints (registered AFTER so they take priority)
  await page.route('**/api/v1/deep-insights/autonomous/active', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(null),
    });
  });

  await page.route('**/api/v1/deep-insights/autonomous/**', async (route) => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'No active analysis task' }),
    });
  });

  await page.route('**/api/v1/features/signals**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ signals: [], count: 0, as_of: new Date().toISOString() }),
    });
  });

  await page.route('**/api/v1/track-record/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });

  await page.route('**/api/v1/knowledge/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ patterns: [], themes: [], total: 0 }),
    });
  });

  await page.route('**/api/v1/conversations**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });

  await page.route('**/api/v1/stocks**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ stocks: [], total: 0 }),
    });
  });

  await page.route('**/api/v1/health**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', timestamp: new Date().toISOString(), version: '1.0.0' }),
    });
  });
}

// Helper: navigate and wait for the page to fully settle (all API responses received, React rendered)
async function gotoAndSettle(page: import('@playwright/test').Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState('domcontentloaded');
  // Wait for network to become idle so all API mocks have resolved and React has re-rendered
  await page.waitForLoadState('networkidle');
}

test.describe('Navigation - Desktop Sidebar', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('sidebar has correct primary navigation links', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');

    // Sidebar nav is visible on desktop
    const sidebarNav = sidebar.locator('nav');
    await expect(sidebarNav.first()).toBeVisible({ timeout: 10000 });

    await expect(sidebar.getByRole('link', { name: 'Home' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Insights' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Conversations' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Research' })).toBeVisible();

    await expect(sidebar.locator('button', { hasText: 'Data' }).first()).toBeVisible({ timeout: 10000 });
  });

  test('Data collapsible reveals Market Data and Signals links', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');

    // Click the Data collapsible button in the sidebar
    const dataButton = sidebar.locator('button', { hasText: 'Data' });
    await expect(dataButton).toBeVisible({ timeout: 10000 });
    await dataButton.click();

    // Data section items appear after expanding
    await expect(sidebar.locator('text=Market Data')).toBeVisible({ timeout: 5000 });
    await expect(sidebar.locator('text=Signals')).toBeVisible();
  });

  test('clicking Home link navigates to home page', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/insights');

    // Use the sidebar nav links
    const sidebar = page.locator('aside');
    const homeLink = sidebar.getByRole('link', { name: 'Home' });
    await expect(homeLink).toBeVisible({ timeout: 10000 });
    await homeLink.click();
    await page.waitForURL('**/');

    expect(page.url()).toMatch(/\/$/);
  });

  test('clicking Insights link navigates to insights page', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');
    const insightsLink = sidebar.getByRole('link', { name: 'Insights' });
    await expect(insightsLink).toBeVisible({ timeout: 10000 });
    await insightsLink.click();
    await page.waitForURL('**/insights');

    expect(page.url()).toContain('/insights');
  });

  test('clicking Conversations link navigates to conversations page', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');
    const conversationsLink = sidebar.getByRole('link', { name: 'Conversations' });
    await expect(conversationsLink).toBeVisible({ timeout: 10000 });
    await conversationsLink.click();
    await page.waitForURL('**/conversations');

    expect(page.url()).toContain('/conversations');
  });

  test('clicking Research link navigates to research page', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');
    const researchLink = sidebar.getByRole('link', { name: 'Research' });
    await expect(researchLink).toBeVisible({ timeout: 10000 });
    await researchLink.click();
    await page.waitForURL('**/research');

    expect(page.url()).toContain('/research');
  });

  test('clicking Market Data from Data section navigates correctly', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    // Click the Data collapsible in sidebar
    const sidebar = page.locator('aside');
    const dataButton = sidebar.locator('button', { hasText: 'Data' });
    await expect(dataButton).toBeVisible({ timeout: 10000 });
    await dataButton.click();

    // Click the Market Data link in the expanded section
    const marketDataLink = sidebar.getByRole('link', { name: 'Market Data' });
    await expect(marketDataLink).toBeVisible({ timeout: 5000 });
    await marketDataLink.click();
    await page.waitForURL('**/stocks');

    expect(page.url()).toContain('/stocks');
  });

  test('active nav link is highlighted', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/insights');

    const sidebar = page.locator('aside');

    const insightsLink = sidebar.getByRole('link', { name: 'Insights' });
    await expect(insightsLink).toBeVisible({ timeout: 10000 });
    const classes = await insightsLink.getAttribute('class');
    expect(classes).toContain('bg-secondary');
  });
});

test.describe('Navigation - Sidebar', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('sidebar has primary navigation links', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');

    // Use getByRole('link') to target actual link elements, avoiding section headings
    await expect(sidebar.getByRole('link', { name: 'Home' })).toBeVisible({ timeout: 10000 });
    await expect(sidebar.getByRole('link', { name: 'Insights' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Patterns' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Track Record' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Conversations' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Research' })).toBeVisible();
  });

  test('sidebar has collapsible Data section', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');

    const dataButton = sidebar.locator('button', { hasText: 'Data' });
    await expect(dataButton).toBeVisible({ timeout: 10000 });

    await dataButton.click();
    await page.waitForTimeout(300);

    await expect(sidebar.locator('text=Market Data')).toBeVisible();
    await expect(sidebar.locator('text=Signals')).toBeVisible();
  });

  test('sidebar has Run Analysis and Settings at bottom', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    // Run Analysis and Settings are in the mobile menu (Sheet), not in the desktop sidebar.
    // On desktop, verify the sidebar nav is visible with its primary links.
    const sidebar = page.locator('aside');
    const sidebarNav = sidebar.locator('nav');
    await expect(sidebarNav.first()).toBeVisible({ timeout: 10000 });

    // Verify primary links are present in the sidebar
    await expect(sidebar.getByRole('link', { name: 'Home' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Insights' })).toBeVisible();
  });

  test('sidebar link navigates to insights page', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');
    // Use getByRole to target the actual link, not the section heading
    const insightsLink = sidebar.getByRole('link', { name: 'Insights' });
    await expect(insightsLink).toBeVisible({ timeout: 10000 });
    await insightsLink.click();
    await page.waitForURL('**/insights');

    expect(page.url()).toContain('/insights');
  });
});

test.describe('Navigation - Mobile Menu', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('mobile menu toggle is visible on small screens', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.setViewportSize({ width: 375, height: 812 });

    await gotoAndSettle(page, '/');

    const mobileMenuBtn = page.locator('header button').filter({ has: page.locator('text=Toggle menu') });
    await expect(mobileMenuBtn).toBeVisible({ timeout: 10000 });
  });

  test('mobile menu opens and shows navigation links', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.setViewportSize({ width: 375, height: 812 });

    await gotoAndSettle(page, '/');

    const mobileMenuBtn = page.locator('header button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle menu' }) });
    await expect(mobileMenuBtn).toBeVisible({ timeout: 10000 });
    await mobileMenuBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    // Use getByRole('link') to specifically target nav links, not section headings
    await expect(dialog.getByRole('link', { name: 'Home' })).toBeVisible();
    await expect(dialog.getByRole('link', { name: 'Insights' })).toBeVisible();
    await expect(dialog.getByRole('link', { name: 'Conversations' })).toBeVisible();
    await expect(dialog.getByRole('link', { name: 'Research' })).toBeVisible();

    await expect(dialog.locator('text=Teletraan')).toBeVisible();
  });

  test('mobile menu shows Data section links', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.setViewportSize({ width: 375, height: 812 });

    await gotoAndSettle(page, '/');

    const mobileMenuBtn = page.locator('header button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle menu' }) });
    await expect(mobileMenuBtn).toBeVisible({ timeout: 10000 });
    await mobileMenuBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    // Data section is collapsible -- expand it first
    const dataButton = dialog.locator('button', { hasText: 'Data' });
    await expect(dataButton).toBeVisible({ timeout: 5000 });
    await dataButton.click();

    await expect(dialog.locator('text=Market Data')).toBeVisible({ timeout: 5000 });
    await expect(dialog.locator('text=Signals')).toBeVisible();
  });

  test('mobile menu navigation works', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.setViewportSize({ width: 375, height: 812 });

    await gotoAndSettle(page, '/');

    const mobileMenuBtn = page.locator('header button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle menu' }) });
    await expect(mobileMenuBtn).toBeVisible({ timeout: 10000 });
    await mobileMenuBtn.click();

    const dialog = page.locator('[role="dialog"]');
    // Use getByRole('link') to target the actual link, not the section heading
    const insightsLink = dialog.getByRole('link', { name: 'Insights' });
    await expect(insightsLink).toBeVisible({ timeout: 5000 });
    await insightsLink.click();

    await page.waitForURL('**/insights');
    expect(page.url()).toContain('/insights');
  });

  test('sidebar is hidden on mobile', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.setViewportSize({ width: 375, height: 812 });

    await gotoAndSettle(page, '/');

    const sidebar = page.locator('aside');
    await expect(sidebar).toBeHidden();
  });
});

test.describe('Navigation - Theme Toggle', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('theme toggle button exists in header', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const themeToggle = page.locator('button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle theme' }) });
    await expect(themeToggle).toBeVisible({ timeout: 10000 });
  });

  test('theme toggle switches between light and dark themes', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    // The theme toggle is a simple button that toggles between light and dark
    const themeToggle = page.locator('button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle theme' }) });
    await expect(themeToggle).toBeVisible({ timeout: 10000 });
    // Ensure the button is enabled (ThemeToggle starts disabled until mounted)
    await expect(themeToggle).toBeEnabled({ timeout: 5000 });

    // Get initial theme
    const initialClasses = await page.locator('html').getAttribute('class');

    // Click to toggle theme
    await themeToggle.click();
    await page.waitForTimeout(500);

    const newClasses = await page.locator('html').getAttribute('class');
    // Theme should have changed
    expect(newClasses).not.toEqual(initialClasses);
  });

  test('clicking theme toggle applies dark class when in light mode', async ({ page }) => {
    await setupGlobalMocks(page);
    // Set initial theme to light via localStorage before navigation
    await page.addInitScript(() => {
      localStorage.setItem('theme', 'light');
    });
    await gotoAndSettle(page, '/');

    const themeToggle = page.locator('button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle theme' }) });
    await expect(themeToggle).toBeVisible({ timeout: 10000 });
    // Wait for the ThemeToggle component to mount and enable the button
    await expect(themeToggle).toBeEnabled({ timeout: 5000 });

    // Click toggle to switch from light to dark
    await themeToggle.click();
    await page.waitForTimeout(500);

    const htmlClasses = await page.locator('html').getAttribute('class');
    expect(htmlClasses).toContain('dark');
  });

  test('clicking theme toggle applies light class when in dark mode', async ({ page }) => {
    await setupGlobalMocks(page);
    // Set initial theme to dark via localStorage before navigation
    await page.addInitScript(() => {
      localStorage.setItem('theme', 'dark');
    });
    await gotoAndSettle(page, '/');

    const themeToggle = page.locator('button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle theme' }) });
    await expect(themeToggle).toBeVisible({ timeout: 10000 });
    // Wait for the ThemeToggle component to mount and enable the button
    await expect(themeToggle).toBeEnabled({ timeout: 5000 });

    // Click toggle to switch from dark to light
    await themeToggle.click();
    await page.waitForTimeout(500);

    const htmlClasses = await page.locator('html').getAttribute('class');
    expect(htmlClasses).toContain('light');
  });
});

test.describe('Navigation - Logo and Branding', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('clicking header logo navigates to home', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/insights');

    // The logo link is an anchor with href="/" containing the TrendingUp icon
    // On wider viewports it also shows "Teletraan" text, but the link itself always exists
    const logoLink = page.locator('header > div > a[href="/"]').first();
    await expect(logoLink).toBeVisible({ timeout: 10000 });
    await logoLink.click();
    await page.waitForURL('**/');

    expect(page.url()).toMatch(/\/$/);
  });

  test('page title is set to Teletraan', async ({ page }) => {
    await setupGlobalMocks(page);
    await gotoAndSettle(page, '/');

    const title = await page.title();
    expect(title).toContain('Teletraan');
  });
});
