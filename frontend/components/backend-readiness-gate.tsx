'use client';

import { useState, useEffect, useCallback, useRef, type ReactNode } from 'react';
import { Loader2, AlertCircle, RefreshCw } from 'lucide-react';

/**
 * Detect whether we are running inside a Tauri desktop shell.
 *
 * tauri.conf.json has `"withGlobalTauri": true` which exposes
 * `window.__TAURI_INTERNALS__` at load time.  We also check
 * `window.__TAURI__` for older Tauri versions.
 */
function isTauriEnvironment(): boolean {
  if (typeof window === 'undefined') return false;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const w = window as any;
  return !!(w.__TAURI_INTERNALS__ || w.__TAURI__);
}

interface BackendReadinessGateProps {
  children: ReactNode;
  /** Maximum number of health check attempts before showing an error. Default: 300 (150 s) */
  maxAttempts?: number;
  /** Interval between health check polls in ms.  Default: 500 */
  pollInterval?: number;
}

type GateState = 'checking' | 'ready' | 'error';

/**
 * When running inside Tauri, this component polls the backend health endpoint
 * and only renders `children` once the backend responds healthy.
 *
 * In the normal web development flow (localhost:3000) it renders children
 * immediately -- the developer is expected to start the backend themselves and
 * individual pages already show "Cannot Reach Backend" when the API is down.
 *
 * The initial state is always 'ready' to avoid hydration mismatches between
 * server-side rendering and client-side hydration.  On mount, if we detect a
 * Tauri environment, we switch to 'checking' and begin polling.
 */
export function BackendReadinessGate({
  children,
  maxAttempts = 300,
  pollInterval = 500,
}: BackendReadinessGateProps) {
  // Always start as 'ready' to match SSR output and avoid hydration mismatch.
  // The useEffect below switches to 'checking' in Tauri after mount.
  const [state, setState] = useState<GateState>('ready');
  const [attempt, setAttempt] = useState(0);
  const [statusText, setStatusText] = useState('Starting backend...');
  const mountedRef = useRef(true);
  const initialCheckDone = useRef(false);

  const checkHealth = useCallback(async (): Promise<boolean> => {
    try {
      // Try normal fetch first
      const resp = await fetch('http://127.0.0.1:8000/api/v1/health', {
        signal: AbortSignal.timeout(3000),
      });
      if (resp.ok) {
        try {
          const body = await resp.json();
          return body?.status === 'healthy';
        } catch {
          return true; // Server responded 200, good enough
        }
      }
      // Server responded but not ok — might be starting up
      return false;
    } catch {
      // Network error or CORS block — try no-cors as fallback
      try {
        const resp = await fetch('http://127.0.0.1:8000/api/v1/health', {
          mode: 'no-cors',
          signal: AbortSignal.timeout(3000),
        });
        // Opaque response (type === 'opaque') means server is responding
        return resp.type === 'opaque' || resp.ok;
      } catch {
        return false; // Server not reachable at all
      }
    }
  }, []);

  const startChecking = useCallback(() => {
    setState('checking');
    setAttempt(0);
    setStatusText('Starting backend...');
  }, []);

  // On mount: detect Tauri environment and begin health-check polling.
  // In non-Tauri (web dev), this is a no-op and children render immediately.
  useEffect(() => {
    if (initialCheckDone.current) return;
    initialCheckDone.current = true;

    if (isTauriEnvironment()) {
      // Do a quick initial check -- if backend is already up (fast startup or
      // Rust health check already passed), skip the splash entirely.
      checkHealth().then((healthy) => {
        if (!mountedRef.current) return;
        if (!healthy) {
          setState('checking');
        }
        // If already healthy, stay in 'ready' -- no flash of loading screen
      });
    }
  }, [checkHealth]);

  // Polling loop: runs whenever state === 'checking'
  useEffect(() => {
    if (state !== 'checking') return;
    mountedRef.current = true;

    let currentAttempt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      if (!mountedRef.current) return;
      currentAttempt++;
      setAttempt(currentAttempt);

      // Update the status text based on progress
      if (currentAttempt <= 4) {
        setStatusText('Starting backend...');
      } else if (currentAttempt <= 20) {
        setStatusText('Backend is loading...');
      } else if (currentAttempt <= 50) {
        setStatusText('Still starting up (this can take a moment)...');
      } else {
        setStatusText('Taking longer than expected...');
      }

      const healthy = await checkHealth();
      if (!mountedRef.current) return;

      if (healthy) {
        setState('ready');
        return;
      }

      if (currentAttempt >= maxAttempts) {
        setState('error');
        return;
      }

      timer = setTimeout(poll, pollInterval);
    };

    poll();

    return () => {
      mountedRef.current = false;
      if (timer) clearTimeout(timer);
    };
  }, [state, checkHealth, maxAttempts, pollInterval]);

  // Ready -- render the app
  if (state === 'ready') {
    return <>{children}</>;
  }

  // Error state -- backend did not start
  if (state === 'error') {
    return (
      <SplashScreen>
        <AlertCircle className="h-8 w-8 text-destructive mb-4" />
        <h2 className="text-lg font-semibold mb-2">Backend Failed to Start</h2>
        <p className="text-sm text-muted-foreground mb-6 max-w-sm text-center">
          The backend service did not become available after {Math.round((maxAttempts * pollInterval) / 1000)} seconds.
          Please check the application logs or restart the app.
        </p>
        <button
          onClick={startChecking}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <RefreshCw className="h-4 w-4" />
          Retry
        </button>
      </SplashScreen>
    );
  }

  // Checking state -- show loading splash
  const progressPercent = Math.min((attempt / maxAttempts) * 100, 95);

  return (
    <SplashScreen>
      <div className="relative mb-6">
        <div className="h-12 w-12 rounded-xl bg-primary/10 flex items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </div>
      </div>
      <h2 className="text-xl font-bold tracking-tight mb-1">Teletraan</h2>
      <p className="text-sm text-muted-foreground mb-6">{statusText}</p>
      {/* Subtle progress bar */}
      <div className="w-48 h-1 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full bg-primary/60 rounded-full transition-all duration-500 ease-out"
          style={{ width: `${progressPercent}%` }}
        />
      </div>
    </SplashScreen>
  );
}

/** Full-screen centered container for splash content. */
function SplashScreen({ children }: { children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-background">
      {children}
    </div>
  );
}
