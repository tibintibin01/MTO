import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "MTO | Public Treasury Portal",
  description: "Securely view your property tax status and payment history.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "MTO Portal",
  },
};

export const viewport: Viewport = {
  themeColor: "#1f4e78",
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
    <html lang="en" className="h-full bg-slate-50">
      <body className={`${inter.className} h-full antialiased`}>
        <div className="min-h-full flex flex-col">
          <header className="bg-[#1f4e78] text-white shadow-lg">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 bg-white rounded-md flex items-center justify-center">
                  <span className="text-[#1f4e78] font-bold">M</span>
                </div>
                <h1 className="font-bold text-lg tracking-tight">TREASURY PORTAL</h1>
              </div>
              <nav className="hidden sm:flex gap-6 text-sm font-medium">
                <a href="/" className="hover:text-blue-200 transition-colors">Property Search</a>
                <a href="/help" className="hover:text-blue-200 transition-colors">Help & Support</a>
              </nav>
            </div>
          </header>
          
          <main className="flex-1">
            {children}
          </main>

          <footer className="bg-white border-t border-slate-200 py-8">
            <div className="max-w-7xl mx-auto px-4 text-center">
              <p className="text-sm text-slate-500">
                &copy; {new Date().getFullYear()} Municipal Treasury Office. All Rights Reserved.
              </p>
              <p className="text-xs text-slate-400 mt-1 uppercase tracking-widest">
                Secure Enterprise Portal
              </p>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
