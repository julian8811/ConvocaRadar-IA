import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { Toaster } from "sonner";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: {
    default: "ConvocaRadar — Observatorio de Convocatorias",
    template: "%s | ConvocaRadar",
  },
  description: "Vigilancia tecnológica institucional de convocatorias nacionales e internacionales de Colmayor",
  // Favicon adaptado de CEITTO/Colmayor: escudo institucional con radar (ver public/brand/README.md)
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/brand/favicon.png", type: "image/png", sizes: "192x192" },
      { url: "/brand/favicon.svg", type: "image/svg+xml" },
      { url: "/icon.png", type: "image/png", sizes: "192x192" },
    ],
    apple: [{ url: "/apple-icon.png", type: "image/png", sizes: "180x180" }],
    shortcut: ["/brand/favicon.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es" className={geistSans.variable} suppressHydrationWarning>
      <body className="bg-[#f3f6fb] font-sans text-slate-950 antialiased dark:bg-[#07111c] dark:text-slate-100">
        {children}
        <Toaster richColors />
      </body>
    </html>
  );
}
