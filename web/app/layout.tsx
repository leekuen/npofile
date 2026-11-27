import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { AuthStatus } from "@/components/auth-status";
import { AuthProvider } from "@/components/auth-provider";
import { SiteNav, SiteNavFallback } from "@/components/site-nav";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "非營利檔案 NPOFile", template: "%s｜非營利檔案 NPOFile" },
  description: "查詢非營利組織的受捐紀錄、捐款專案與受裁罰紀錄",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-Hant-TW" className="h-full antialiased">
      <body className="flex min-h-full flex-col font-sans">
        <AuthProvider>
          <header className="border-b border-slate-200 bg-white">
            <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3">
              <div className="flex items-center gap-4">
                <Link href="/" className="flex items-baseline gap-2 font-bold text-slate-900">
                  <span className="text-lg">非營利檔案</span>
                  <span className="hidden text-sm font-semibold text-teal-700 sm:inline">NPOFile</span>
                </Link>
                <Suspense fallback={<SiteNavFallback />}>
                  <SiteNav />
                </Suspense>
              </div>
              <AuthStatus />
            </div>
          </header>
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">{children}</main>
          <footer className="border-t border-slate-200 bg-white">
            <div className="mx-auto max-w-5xl px-4 py-4 text-xs text-slate-600">
              資料來源：衛生福利部公益勸募管理系統（含捐贈人清冊）、財政部非營利事業機關團體資料集、經濟部商工登記公示資料（政府資料開放授權）。資料以各來源公告為準。
            </div>
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
