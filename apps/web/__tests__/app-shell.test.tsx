/**
 * SEC-1.5 frontend: app-shell AbortError UX.
 *
 * Contract (from spec / design):
 *   - useQuery for me: retry: 1, retryDelay: 1000ms.
 *   - On AbortError (network timeout): show a clear "No se pudo contactar al
 *     servidor" error and a "Reintentar" button. Do NOT redirect immediately.
 *   - The Reintentar button refetches `me` once. If it fails again, redirect
 *     to /login with query param ?reason=session_expired.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ReactNode } from "react";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

const mockReplace = vi.fn();
const mockPush = vi.fn();
const mockUsePathname = vi.fn(() => "/dashboard");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, refresh: vi.fn(), replace: mockReplace }),
  usePathname: () => mockUsePathname(),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children: React.ReactNode; href: string; className?: string }) =>
    <a {...props}>{children}</a>,
}));

// Explicit lucide-react stubs. We use explicit names (not a Proxy) because
// a Proxy mock of this module triggers an infinite import loop in vitest.
vi.mock("lucide-react", () => {
  const Stub: React.FC<{ className?: string }> = (props) => <svg data-testid="icon-stub" className={props.className} />;
  return {
    AlertTriangle: Stub,
    Bell: Stub,
    Database: Stub,
    FileText: Stub,
    Gauge: Stub,
    Loader2: Stub,
    LogOut: Stub,
    Menu: Stub,
    Moon: Stub,
    Radar: Stub,
    RefreshCw: Stub,
    Search: Stub,
    Settings: Stub,
    Shield: Stub,
    SunMedium: Stub,
    Target: Stub,
    UserRound: Stub,
  };
});

const mockApiMe = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    me: (...args: unknown[]) => mockApiMe(...args),
    logout: vi.fn().mockResolvedValue({ detail: "ok" }),
  },
  getToken: vi.fn(() => "test-token"),
  clearToken: vi.fn(),
  setToken: vi.fn(),
}));

async function loadAppShell() {
  vi.resetModules();
  const mod = await import("@/components/app-shell");
  return mod.AppShell;
}

function makeAbortError() {
  const err = new Error("aborted");
  err.name = "AbortError";
  return err;
}

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, retryDelay: 0 },
    },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

describe("AppShell — AbortError handling (SEC-1.5)", () => {
  beforeEach(() => {
    mockReplace.mockReset();
    mockPush.mockReset();
    mockApiMe.mockReset();
  });

  it("shows the 'No se pudo contactar al servidor' error and a 'Reintentar' button on AbortError (does NOT redirect immediately)", async () => {
    mockApiMe.mockRejectedValue(makeAbortError());

    const AppShell = await loadAppShell();
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <AppShell>
          <div>child</div>
        </AppShell>
      </Wrapper>,
    );

    // The error message must appear after the initial fetch + 1 retry (delay 1s).
    await waitFor(() => {
      expect(screen.getByText(/No se pudo contactar al servidor/i)).toBeDefined();
    }, { timeout: 5000 });
    // The Reintentar button must appear
    expect(screen.getByRole("button", { name: /Reintentar/i })).toBeDefined();
    // Must NOT have redirected to /login yet
    expect(mockReplace).not.toHaveBeenCalledWith("/login");
  });

  it("uses retry: 1 with retryDelay: 1000 on the me query (does not infinite-loop)", async () => {
    let callCount = 0;
    mockApiMe.mockImplementation(() => {
      callCount += 1;
      return Promise.reject(makeAbortError());
    });

    const AppShell = await loadAppShell();
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <AppShell>
          <div>child</div>
        </AppShell>
      </Wrapper>,
    );

    // Wait for the query to settle. We expect ONE initial call plus ONE retry.
    await waitFor(
      () => {
        expect(screen.getByText(/No se pudo contactar al servidor/i)).toBeDefined();
      },
      { timeout: 5000 },
    );

    // The queryFn should have been called at least 2 times (initial + 1 retry)
    // but not more than 3 (we don't want infinite loops). Use a tight bound.
    expect(callCount).toBeGreaterThanOrEqual(2);
    expect(callCount).toBeLessThanOrEqual(3);
  });

  it("clicking 'Reintentar' refetches me; second AbortError redirects to /login?reason=session_expired", async () => {
    mockApiMe.mockRejectedValue(makeAbortError());

    const AppShell = await loadAppShell();
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <AppShell>
          <div>child</div>
        </AppShell>
      </Wrapper>,
    );

    // Wait for first error to show (initial + 1 retry = ~1s)
    await waitFor(() => {
      expect(screen.getByText(/No se pudo contactar al servidor/i)).toBeDefined();
    }, { timeout: 5000 });
    const retryBtn = await screen.findByRole("button", { name: /Reintentar/i });
    fireEvent.click(retryBtn);

    // After the manual retry fails, the user must be redirected to /login with reason
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login?reason=session_expired");
    }, { timeout: 5000 });
  });

  it("on a non-AbortError, redirects to /login without showing the retry UI", async () => {
    const err = new Error("Invalid token");
    err.name = "Error";
    mockApiMe.mockRejectedValue(err);

    const AppShell = await loadAppShell();
    const Wrapper = makeWrapper();
    render(
      <Wrapper>
        <AppShell>
          <div>child</div>
        </AppShell>
      </Wrapper>,
    );

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    }, { timeout: 5000 });
    // The retry UI must NOT be shown for non-AbortError
    expect(screen.queryByText(/No se pudo contactar al servidor/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Reintentar/i })).toBeNull();
  });
});
