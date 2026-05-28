import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastProvider } from "./components/ToastProvider";
import { OfflineBanner } from "./components/OfflineBanner";
import { PublicShell } from "./components/PublicShell";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Dipaculao Treasury Portal | Bayan ng Dipaculao, Aurora",
  description: "Official property tax portal of the Municipal Treasury Office of Dipaculao, Aurora.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Dipaculao Treasury",
  },
};

export const viewport: Viewport = {
  themeColor: "#1a3a6b",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.className} h-full antialiased bg-[#f0f4f8]`}>
        <ToastProvider>
          <OfflineBanner />
          <ErrorBoundary>
            {/* PublicShell renders header+footer only on non-admin routes.
                Admin routes (/admin/*) have their own full-screen layout. */}
            <PublicShell>
              {children}
            </PublicShell>
          </ErrorBoundary>
        </ToastProvider>
      </body>
    </html>
  );
}
