import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/login",
}));

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children: React.ReactNode; href: string; className?: string }) =>
    <a {...props}>{children}</a>,
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Mock lucide-react — provide all icons used in the component tree
vi.mock("lucide-react", () => ({
  Radar: () => <svg data-testid="icon-Radar" />,
  Moon: () => <svg data-testid="icon-Moon" />,
  SunMedium: () => <svg data-testid="icon-SunMedium" />,
}));

// Mock API module
vi.mock("@/lib/api", () => ({
  API_URL: "http://test.local/api/v1",
  api: { login: vi.fn().mockResolvedValue({ access_token: "test-token" }) },
  setToken: vi.fn(),
  getToken: vi.fn(() => null),
}));

describe("Login Page - Dev credentials gating", () => {
  it("hides local credentials button in production", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_LOCAL_EMAIL", "");
    vi.stubEnv("NEXT_PUBLIC_LOCAL_PASSWORD", "");
    vi.resetModules();

    // Dynamic import so env is read after being set
    const { default: LoginPage } = await import("@/app/login/page");
    render(<LoginPage />);

    // The "Entrar con cuenta local" button must NOT be rendered
    expect(screen.queryByText("Entrar con cuenta local")).toBeNull();

    // The submit button must NOT have data-testid="login-submit"
    expect(screen.queryByTestId("login-submit")).toBeNull();
  });

  it("shows local credentials button in development", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_LOCAL_EMAIL", "dev@test.io");
    vi.stubEnv("NEXT_PUBLIC_LOCAL_PASSWORD", "devpass123");
    vi.resetModules();

    const { default: LoginPage } = await import("@/app/login/page");
    render(<LoginPage />);

    // The "Entrar con cuenta local" button MUST be rendered in dev
    expect(screen.getByText("Entrar con cuenta local")).toBeDefined();
  });

  it("does not have data-testid='login-submit' on the submit button", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENV", "development");
    vi.resetModules();

    const { default: LoginPage } = await import("@/app/login/page");
    render(<LoginPage />);

    // The submit button should NOT have the data-testid attribute
    const submitBtn = screen.queryByTestId("login-submit");
    expect(submitBtn).toBeNull();

    // But the regular submit button should still be there
    expect(screen.getByText("Ingresar")).toBeDefined();
  });
});
