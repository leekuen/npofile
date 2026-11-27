"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "./auth-provider";

export function AuthStatus() {
  const { user, loading, logout } = useAuth();
  const [busy, setBusy] = useState(false);

  if (loading) return <span className="h-5 w-20 animate-pulse rounded bg-ink-100" aria-hidden />;

  if (!user) {
    return (
      <nav className="flex items-center gap-1 text-sm whitespace-nowrap sm:gap-2">
        <Link href="/login" className="rounded-full px-2 py-2 text-ink-700 hover:bg-ink-100 sm:px-3">
          登入
        </Link>
        <Link href="/register" className="rounded-full border border-ink-300 px-2.5 py-2 font-medium text-ink-800 hover:bg-ink-50 sm:px-3">
          註冊
        </Link>
      </nav>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="max-w-[10rem] truncate text-ink-700" title={user.display_name}>
        {user.display_name}
      </span>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await logout();
          } finally {
            setBusy(false);
          }
        }}
        className="rounded-full px-3 py-2 text-ink-700 hover:bg-ink-100 disabled:opacity-50"
      >
        登出
      </button>
    </div>
  );
}
