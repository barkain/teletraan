import { test, expect } from './fixtures';

// Helper to set up standard API mocks so pages render without real backend
async function setupGlobalMocks(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/deep-insights**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });

  await page.route('**/api/v1/deep-insights/autonomous/status**', async (route) => {
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

test.describe('Navigation - Desktop Header', () => {
  test.beforeEach(async ({ page }) => {
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        console.log('CONSOLE ERROR:', msg.text());
      }
    });
  });

  test('header has correct primary navigation links', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const header = page.locator('header');

    // Desktop nav is the visible nav element inside header
    const desktopNav = header.locator('nav');
    await expect(desktopNav.first()).toBeVisible({ timeout: 10000 });

    await expect(header.locator('a', { hasText: 'Home' }).first()).toBeVisible();
    await expect(header.locator('a', { hasText: 'Insights' }).first()).toBeVisible();
    await expect(header.locator('a', { hasText: 'Conversations' }).first()).toBeVisible();
    await expect(header.locator('a', { hasText: 'Research' }).first()).toBeVisible();

    await expect(header.locator('button', { hasText: 'Data' }).first()).toBeVisible();
  });

  test('Data dropdown reveals Market Data and Signals links', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const header = page.locator('header');

    // Click the Data dropdown button in the desktop nav
    const dataButton = header.locator('nav button', { hasText: 'Data' });
    await expect(dataButton).toBeVisible({ timeout: 10000 });
    await dataButton.click();

    // Dropdown menu items appear as role="menuitem" in the dropdown content
    await expect(page.locator('[role="menuitem"]', { hasText: 'Market Data' })).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[role="menuitem"]', { hasText: 'Signals' })).toBeVisible();
  });

  test('clicking Home link navigates to home page', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/insights');
    await page.waitForLoadState('domcontentloaded');

    // Use the desktop nav links (inside header > nav)
    const desktopNav = page.locator('header nav');
    const homeLink = desktopNav.locator('a', { hasText: 'Home' }).first();
    await expect(homeLink).toBeVisible({ timeout: 10000 });
    await homeLink.click();
    await page.waitForURL('**/');

    expect(page.url()).toMatch(/\/$/);
  });

  test('clicking Insights link navigates to insights page', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const desktopNav = page.locator('header nav');
    const insightsLink = desktopNav.locator('a', { hasText: 'Insights' }).first();
    await expect(insightsLink).toBeVisible({ timeout: 10000 });
    await insightsLink.click();
    await page.waitForURL('**/insights');

    expect(page.url()).toContain('/insights');
  });

  test('clicking Conversations link navigates to conversations page', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const desktopNav = page.locator('header nav');
    const conversationsLink = desktopNav.locator('a', { hasText: 'Conversations' }).first();
    await expect(conversationsLink).toBeVisible({ timeout: 10000 });
    await conversationsLink.click();
    await page.waitForURL('**/conversations');

    expect(page.url()).toContain('/conversations');
  });

  test('clicking Research link navigates to research page', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const desktopNav = page.locator('header nav');
    const researchLink = desktopNav.locator('a', { hasText: 'Research' }).first();
    await expect(researchLink).toBeVisible({ timeout: 10000 });
    await researchLink.click();
    await page.waitForURL('**/research');

    expect(page.url()).toContain('/research');
  });

  test('clicking Market Data from Data dropdown navigates correctly', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Click the Data dropdown in header nav
    const dataButton = page.locator('header nav button', { hasText: 'Data' });
    await expect(dataButton).toBeVisible({ timeout: 10000 });
    await dataButton.click();

    // Click the Market Data menu item in the dropdown
    const marketDataItem = page.locator('[role="menuitem"]', { hasText: 'Market Data' });
    await expect(marketDataItem).toBeVisible({ timeout: 5000 });
    await marketDataItem.click();
    await page.waitForURL('**/stocks');

    expect(page.url()).toContain('/stocks');
  });

  test('active nav link is highlighted', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/insights');
    await page.waitForLoadState('domcontentloaded');

    const header = page.locator('header');

    const insightsLink = header.locator('nav a', { hasText: 'Insights' }).first();
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
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

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
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

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
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const sidebar = page.locator('aside');

    await expect(sidebar.locator('text=Run Analysis')).toBeVisible({ timeout: 10000 });
    await expect(sidebar.locator('text=Settings')).toBeVisible();
  });

  test('sidebar link navigates to insights page', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

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

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const mobileMenuBtn = page.locator('header button').filter({ has: page.locator('text=Toggle menu') });
    await expect(mobileMenuBtn).toBeVisible({ timeout: 10000 });
  });

  test('mobile menu opens and shows navigation links', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.setViewportSize({ width: 375, height: 812 });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

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

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const mobileMenuBtn = page.locator('header button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle menu' }) });
    await mobileMenuBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog.locator('text=Market Data')).toBeVisible({ timeout: 5000 });
    await expect(dialog.locator('text=Signals')).toBeVisible();
  });

  test('mobile menu navigation works', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.setViewportSize({ width: 375, height: 812 });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const mobileMenuBtn = page.locator('header button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle menu' }) });
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

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

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
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const themeToggle = page.locator('button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle theme' }) });
    await expect(themeToggle).toBeVisible({ timeout: 10000 });
  });

  test('theme toggle opens dropdown with Light, Dark, System options', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const themeToggle = page.locator('button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle theme' }) });
    await expect(themeToggle).toBeVisible({ timeout: 10000 });
    await themeToggle.click();

    await expect(page.locator('[role="menuitem"]', { hasText: 'Light' })).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[role="menuitem"]', { hasText: 'Dark' })).toBeVisible();
    await expect(page.locator('[role="menuitem"]', { hasText: 'System' })).toBeVisible();
  });

  test('selecting Dark theme applies dark class', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const themeToggle = page.locator('button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle theme' }) });
    await themeToggle.click();

    const darkOption = page.locator('[role="menuitem"]', { hasText: 'Dark' });
    await expect(darkOption).toBeVisible({ timeout: 5000 });
    await darkOption.click();

    await page.waitForTimeout(500);

    const htmlClasses = await page.locator('html').getAttribute('class');
    expect(htmlClasses).toContain('dark');
  });

  test('selecting Light theme applies light class', async ({ page }) => {
    await setupGlobalMocks(page);
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const themeToggle = page.locator('button').filter({ has: page.locator('.sr-only', { hasText: 'Toggle theme' }) });
    await themeToggle.click();

    const lightOption = page.locator('[role="menuitem"]', { hasText: 'Light' });
    await expect(lightOption).toBeVisible({ timeout: 5000 });
    await lightOption.click();

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
    await page.goto('/insights');
    await page.waitForLoadState('domcontentloaded');

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
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const title = await page.title();
    expect(title).toContain('Teletraan');
  });
});
