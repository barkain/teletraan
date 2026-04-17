'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { setAccessToken } from '@/lib/auth-store';

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/api\/v1\/?$/, '');

// Access tokens are 15 min; refresh 2 min early.
const REFRESH_INTERVAL_MS = 13 * 60 * 1000;

interface AuthUser {
  username: string;
  is_active: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        });
        if (res.ok) {
          const data = await res.json();
          setAccessToken(data.access_token);
          scheduleRefresh();
        } else {
          // Refresh failed — clear session
          setAccessToken(null);
          setUser(null);
        }
      } catch {
        setAccessToken(null);
        setUser(null);
      }
    }, REFRESH_INTERVAL_MS);
  }, []);

  // On mount: try to restore session via the httpOnly refresh cookie
  useEffect(() => {
    async function restoreSession() {
      try {
        // First refresh to get a fresh access token
        const refreshRes = await fetch(`${API_URL}/api/v1/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        });
        if (!refreshRes.ok) {
          setIsLoading(false);
          return;
        }
        const refreshData = await refreshRes.json();
        setAccessToken(refreshData.access_token);

        // Then fetch user info
        const meRes = await fetch(`${API_URL}/api/v1/auth/me`, {
          credentials: 'include',
        });
        if (meRes.ok) {
          const userData: AuthUser = await meRes.json();
          setUser(userData);
          scheduleRefresh();
        }
      } catch {
        // Network error or no session — stay logged out
      } finally {
        setIsLoading(false);
      }
    }
    restoreSession();

    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, [scheduleRefresh]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await fetch(`${API_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body?.detail || 'Login failed');
    }
    const data = await res.json();
    setAccessToken(data.access_token);

    const meRes = await fetch(`${API_URL}/api/v1/auth/me`, {
      credentials: 'include',
    });
    if (meRes.ok) {
      const userData: AuthUser = await meRes.json();
      setUser(userData);
      scheduleRefresh();
    }
  }, [scheduleRefresh]);

  const logout = useCallback(async () => {
    try {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      });
    } catch {
      // Best-effort
    }
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    setAccessToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
