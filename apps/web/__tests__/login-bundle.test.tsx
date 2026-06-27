/**
 * SEC-1.5: bundle hardening — verify that the production login page does not
 * contain any hardcoded credential strings, even when the localStorage /
 * env values would carry them in dev. (This is a render-time check; the
 * Next.js prod build also bakes NEXT_PUBLIC_* values into the JS bundle,
 * so a separate grep of the built output is the canonical check.)
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
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
  api: { login: vi.fn().mockResolvedValue({ access_token: "x" }) },
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
