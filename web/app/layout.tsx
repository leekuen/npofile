import type { Metadata } from "next";
import { Chiron_GoRound_TC, Inter, Noto_Sans_TC } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";

import { AuthStatus } from "@/components/auth-status";
import { AuthProvider } from "@/components/auth-provider";
import { SiteNav, SiteNavFallback } from "@/components/site-nav";
import { GRANT_AGENCIES } from "@/lib/sources";

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
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-xl focus:bg-white focus:px-4 focus:py-2 focus:shadow"
          >
            跳到主要內容
          </a>
          <header className="sticky top-0 z-30 border-b border-ink-200/80 bg-white/85 backdrop-blur supports-[backdrop-filter]:bg-white/75">
            <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-2.5 sm:px-6">
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
          <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
            {children}
          </main>
          <footer className="mt-8 border-t border-ink-200 bg-white">
            <div className="mx-auto grid max-w-6xl gap-6 px-4 py-8 sm:px-6 md:grid-cols-[16rem_minmax(0,1fr)] md:gap-12">
              <div className="space-y-3">
                <p className="flex items-center gap-2 font-display font-bold text-ink-900">
                  <span aria-hidden className="grid h-7 w-7 place-items-center rounded-lg bg-brand-700 text-sm text-white">
                    檔
                  </span>
                  非營利檔案
                </p>
                <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                  <li>
                    <Link href="/" className="text-ink-700 hover:text-brand-800 hover:underline">
                      組織
                    </Link>
                  </li>
                  <li>
                    <Link href="/donors" className="text-ink-700 hover:text-brand-800 hover:underline">
                      捐款企業
                    </Link>
                  </li>
                  <li>
                    <Link href="/about" className="text-ink-700 hover:text-brand-800 hover:underline">
                      資料說明
                    </Link>
                  </li>
                </ul>
              </div>
              <p className="text-xs leading-relaxed text-ink-600">
                <span className="font-semibold text-ink-700">資料來源</span>
                <span aria-hidden className="mx-1.5 text-ink-300">
                  |
                </span>
                衛生福利部公益勸募管理系統（含捐贈人清冊）、{GRANT_AGENCIES}的補(捐)助季報、臺北市政府勞動局違反勞動基準法事業單位公布總表、勞動部違反勞動法令事業單位查詢系統、環境部列管事業污染源裁處資料、財政部非營利事業機關團體資料集、經濟部商工登記公示資料（政府資料開放授權）；挖貝 WaBay 群眾集資專案頁。資料以各來源公告為準。
              </p>
            </div>
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
