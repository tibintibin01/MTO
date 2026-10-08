import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastProvider } from "./components/ToastProvider";
import { OfflineBanner } from "./components/OfflineBanner";
import { PublicShell } from "./components/PublicShell";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Public Treasury Web Portal | Bayan ng Dipaculao, Aurora",
  applicationName: "Public Treasury Web Portal",
  description: "Official property tax portal of the Municipal Treasury Office of Dipaculao, Aurora.",
  manifest: "/manifest.json",
  icons: {
    icon: [
      { url: "/icons/portal-20261008/icon-16.png", sizes: "16x16", type: "image/png" },
      { url: "/icons/portal-20261008/icon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/icons/portal-20261008/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/portal-20261008/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/portal-20261008/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Public Treasury Web Portal",
  },
};

export const viewport: Viewport = {
  themeColor: "#1a3a6b",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.className} h-full antialiased bg-[#f0f4f8]`}>
        <a href="#main-content" className="skip-link">Skip to main content</a>
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
