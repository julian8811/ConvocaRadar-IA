import type { Metadata } from "next";
import Script from "next/script";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "sonner";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Observatorio de Convocatorias Institucional",
  description: "Vigilancia tecnológica institucional de convocatorias nacionales e internacionales de Colmayor",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es" className={`${geistSans.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <head>
      </head>
      <body className="bg-[#f3f6fb] font-sans text-slate-950 antialiased dark:bg-[#07111c] dark:text-slate-100">
        <Script
          id="keep-alive"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                var apiUrl = document.querySelector('meta[name="api-url"]')?.getAttribute('content') || '${process.env.NEXT_PUBLIC_API_URL || ""}';
                if (!apiUrl) return;
                // Ping every 10 minutes to keep Render free tier awake
                function ping() {
                  fetch(apiUrl + '/health', { method: 'GET', mode: 'no-cors' }).catch(function(){});
                }
                ping();
                setInterval(ping, 600000);
              })();
            `,
          }}
        />
        {children}
        <Toaster richColors />
      </body>
    </html>
  );
}
