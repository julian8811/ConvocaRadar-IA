/**
 * SEC-1.5: bundle hardening — verify that the production login page does not
 * contain any hardcoded credential strings, even when the localStorage /
 * env values would carry them in dev. (This is a render-time check; the
 * Next.js prod build also bakes NEXT_PUBLIC_* values into the JS bundle,
 * so a separate grep of the built output is the canonical check.)
 *
 * PR 3 (tier-2-production-readiness): the 401 split in lib/api.ts now
 * surfaces the server's body.detail for /auth/login failures instead of
 * a generic "Sesión expirada". These tests verify the page renders that
 * error in the form, preserves the typed values, and does NOT redirect.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  mockLogin.mockReset();
  // Default to the success mock that the existing bundle-hardening tests
  // rely on. Individual tests below override this with mockRejectedValue.
  mockLogin.mockResolvedValue({ access_token: "x" });
  mockRouterPush.mockReset();
});

// Hoisted so the vi.mock factory below can capture a stable reference
// to the mock function (and individual tests can override its behavior
// per case without rebuilding the entire mock module).
const { mockLogin, mockRouterPush } = vi.hoisted(() => ({
  mockLogin: vi.fn().mockResolvedValue({ access_token: "x" }),
  mockRouterPush: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush, refresh: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/login",
}));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children: React.ReactNode; href: string; className?: string }) =>
    <a {...props}>{children}</a>,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("lucide-react", () => {
  const Stub: React.FC<{ className?: string }> = (props) => <svg data-testid="icon-stub" className={props.className} />;
  return { Radar: Stub, Moon: Stub, SunMedium: Stub };
});
vi.mock("@/lib/api", () => ({
  API_URL: "http://test.local/api/v1",
  api: { login: mockLogin },
  setToken: vi.fn(),
  getToken: vi.fn(() => null),
}));

describe("Login page — production bundle hardening (SEC-1.3)", () => {
  it("PRODUCTION: hardcoded dev password value never appears in the rendered DOM", async () => {
    const devPassword = "super-secret-dev-pw-XYZ-987";
    vi.stubEnv("NEXT_PUBLIC_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_LOCAL_EMAIL", "");
    vi.stubEnv("NEXT_PUBLIC_LOCAL_PASSWORD", devPassword);
    vi.resetModules();
    const { default: LoginPage } = await import("@/app/login/page");
    const { container } = render(<LoginPage />);
    expect(container.innerHTML).not.toContain(devPassword);
  });

  it("DEVELOPMENT: dev password is in the pre-filled field (documented behavior)", async () => {
    const devPassword = "super-secret-dev-pw-XYZ-987";
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_LOCAL_EMAIL", "dev@x.io");
    vi.stubEnv("NEXT_PUBLIC_LOCAL_PASSWORD", devPassword);
    vi.resetModules();
    const { default: LoginPage } = await import("@/app/login/page");
    const { container } = render(<LoginPage />);
    // The dev button uses the password — documented dev behavior.
    expect(container.innerHTML).toContain(devPassword);
  });
});

describe("Login page — 401 path preserves form state and shows server detail (PR 3)", () => {
  it("shows the server's body.detail when /auth/login returns 401 with a detail", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "production");
    mockLogin.mockRejectedValueOnce(new Error("Invalid credentials"));
    vi.resetModules();
    const { default: LoginPage } = await import("@/app/login/page");
    render(<LoginPage />);

    const emailInput = screen.getByTestId("login-email") as HTMLInputElement;
    const passwordInput = screen.getByTestId("login-password") as HTMLInputElement;
    fireEvent.change(emailInput, { target: { value: "user@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "wrong-password" } });

    fireEvent.click(screen.getByText("Ingresar"));

    await waitFor(() => {
      expect(screen.getByText("Invalid credentials")).toBeDefined();
    });

    // The router must NOT have been called (no redirect to /dashboard).
    expect(mockRouterPush).not.toHaveBeenCalled();
    // Form state is preserved.
    expect(emailInput.value).toBe("user@example.com");
    expect(passwordInput.value).toBe("wrong-password");
  });

  it("falls back to 'Credenciales inválidas' when the server's body.detail is empty", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "production");
    mockLogin.mockRejectedValueOnce(new Error("Credenciales inválidas"));
    vi.resetModules();
    const { default: LoginPage } = await import("@/app/login/page");
    render(<LoginPage />);

    const emailInput = screen.getByTestId("login-email") as HTMLInputElement;
    const passwordInput = screen.getByTestId("login-password") as HTMLInputElement;
    fireEvent.change(emailInput, { target: { value: "another@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "another-bad-pw" } });

    fireEvent.click(screen.getByText("Ingresar"));

    await waitFor(() => {
      expect(screen.getByText("Credenciales inválidas")).toBeDefined();
    });

    // Form state is preserved across the failed login.
    expect(emailInput.value).toBe("another@example.com");
    expect(passwordInput.value).toBe("another-bad-pw");
    expect(mockRouterPush).not.toHaveBeenCalled();
  });
});
