import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { Toaster } from "sonner";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Observatorio de Convocatorias Institucional",
  description: "Vigilancia tecnológica institucional de convocatorias nacionales e internacionales de Colmayor",
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
