import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';
import { ThemeProvider } from '@/components/theme-provider';
import { Providers } from '@/lib/providers';
import { Header } from '@/components/layout/header';
import { Sidebar } from '@/components/layout/sidebar';
import { BackendReadinessGate } from '@/components/backend-readiness-gate';
import { AuthProvider } from '@/contexts/auth-context';
import { AuthGate } from '@/components/auth-gate';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'Teletraan',
  description: 'AI-Powered Market Intelligence',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <Providers>
            <AuthProvider>
              <BackendReadinessGate>
                <AuthGate>
                  <div className="relative flex min-h-screen flex-col">
                    <Header />
                    <div className="flex flex-1">
                      <Sidebar />
                      <main className="flex-1 p-6">{children}</main>
                    </div>
                  </div>
                </AuthGate>
              </BackendReadinessGate>
            </AuthProvider>
          </Providers>
        </ThemeProvider>
      </body>
    </html>
  );
}
