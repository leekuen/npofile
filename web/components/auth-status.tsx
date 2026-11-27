"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "./auth-provider";

export function AuthStatus() {
  const { user, loading, logout } = useAuth();
  const [busy, setBusy] = useState(false);

  if (loading) return <span className="h-5 w-20 animate-pulse rounded bg-slate-100" aria-hidden />;

  if (!user) {
    return (
      <nav className="flex items-center gap-2 text-sm">
        <Link href="/login" className="rounded px-3 py-2 text-slate-700 hover:bg-slate-100">
          登入
        </Link>
        <Link href="/register" className="rounded border border-slate-300 px-3 py-2 font-medium text-slate-800 hover:bg-slate-50">
          註冊
        </Link>
      </nav>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="max-w-[10rem] truncate text-slate-700" title={user.display_name}>
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
        className="rounded px-3 py-2 text-slate-700 hover:bg-slate-100 disabled:opacity-50"
      >
        登出
      </button>
    </div>
  );
}
