import type { Metadata } from "next";
import Script from "next/script";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "sonner";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ConvocaRadar IA",
  description: "Vigilancia inteligente de convocatorias y financiación",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es" className={`${geistSans.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <head>
        <Script
          id="theme-init"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var stored = localStorage.getItem("convocaradar-theme");
                  var prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
                  var theme = stored === "light" || stored === "dark" ? stored : (prefersDark ? "dark" : "light");
                  document.documentElement.classList.toggle("dark", theme === "dark");
                } catch (error) {}
              })();
            `,
          }}
        />
      </head>
      <body className="bg-[#f3f6fb] font-sans text-slate-950 antialiased dark:bg-[#07111c] dark:text-slate-100">
        {children}
        <Toaster richColors />
      </body>
    </html>
  );
}
