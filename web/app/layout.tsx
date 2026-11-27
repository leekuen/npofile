import type { Metadata } from "next";
import { Chiron_GoRound_TC, Inter, Noto_Sans_TC } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";

import { AuthStatus } from "@/components/auth-status";
import { AuthProvider } from "@/components/auth-provider";
import { SiteNav, SiteNavFallback } from "@/components/site-nav";

import "./globals.css";

// 中文字型很大，Google 會切成多段 unicode-range，瀏覽器只下載頁面用到的字；不預載以免拖慢首屏
const notoSansTC = Noto_Sans_TC({ subsets: ["latin"], variable: "--font-noto-sans-tc", preload: false, display: "swap" });
const goRound = Chiron_GoRound_TC({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-goround", preload: false, display: "swap", adjustFontFallback: false });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: { default: "非營利檔案 NPOFile", template: "%s｜非營利檔案 NPOFile" },
  description: "查詢非營利組織的受捐紀錄、捐款專案與受裁罰紀錄",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-Hant-TW" className={`h-full antialiased ${notoSansTC.variable} ${goRound.variable} ${inter.variable}`}>
      <body className="flex min-h-full flex-col font-sans">
        <AuthProvider>
          <header className="border-b border-ink-200 bg-white">
            <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3 sm:gap-5">
                <Link href="/" className="flex shrink-0 items-center gap-2 text-ink-900">
                  <span
                    aria-hidden
                    className="grid h-8 w-8 place-items-center rounded-xl bg-brand-700 font-display text-base font-bold text-white"
                  >
                    檔
                  </span>
                  <span className="hidden font-display text-xl font-bold sm:inline">非營利檔案</span>
                  <span className="sr-only sm:hidden">非營利檔案</span>
                </Link>
                <Suspense fallback={<SiteNavFallback />}>
                  <SiteNav />
                </Suspense>
              </div>
              <AuthStatus />
            </div>
          </header>
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
          <footer className="border-t border-ink-200 bg-white">
            <div className="mx-auto max-w-5xl px-4 py-5 text-xs text-ink-600">
              資料來源：衛生福利部公益勸募管理系統（含捐贈人清冊）、衛生福利部對民間團體及個人補(捐)助經費彙總表、勞動部就業安定基金補(捐)助季報表、財政部非營利事業機關團體資料集、經濟部商工登記公示資料（政府資料開放授權）；挖貝 WaBay 群眾集資專案頁。資料以各來源公告為準。
            </div>
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
