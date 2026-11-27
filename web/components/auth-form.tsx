"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ApiError, api } from "@/lib/client-api";
import type { Me } from "@/lib/types";

import { useAuth } from "./auth-provider";

const inputCls =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-teal-600 focus:outline-none aria-invalid:border-red-600";

function safeNext(next: string | null) {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setUser } = useAuth();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fields, setFields] = useState<Record<string, string[]>>({});

  const isRegister = mode === "register";
  const next = safeNext(searchParams.get("next"));
  const canSubmit = email.trim() && password && (!isRegister || displayName.trim()) && !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    setFields({});
    try {
      const body = isRegister
        ? { email: email.trim(), display_name: displayName.trim(), password }
        : { email: email.trim(), password };
      const r = await api<{ user: Me }>(isRegister ? "/api/auth/register" : "/api/auth/login", { method: "POST", body });
      setUser(r.user);
      router.push(next);
    } catch (err) {
      if (err instanceof ApiError) {
        setFields(err.fields);
        if (!Object.keys(err.fields).length) setError(err.message);
      } else {
        setError("發生錯誤，請再試一次");
      }
    } finally {
      setBusy(false);
    }
  }

  const fieldError = (name: string) =>
    fields[name]?.length ? (
      <span id={`${name}-error`} className="mt-1 block text-xs text-red-800">
        {fields[name].join(" ")}
      </span>
    ) : null;

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">Email</span>
        <input
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={inputCls}
          aria-invalid={fields.email ? true : undefined}
          aria-describedby={fields.email ? "email-error" : undefined}
        />
        {fieldError("email")}
      </label>
      {isRegister && (
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-700">顯示名稱</span>
          <input
            type="text"
            autoComplete="nickname"
            maxLength={50}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className={inputCls}
            aria-invalid={fields.display_name ? true : undefined}
            aria-describedby="display-name-hint"
          />
          <span id="display-name-hint" className="mt-1 block text-xs text-slate-500">
            留言時顯示這個名稱，Email 不會公開。
          </span>
          {fieldError("display_name")}
        </label>
      )}
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">密碼</span>
        <input
          type="password"
          autoComplete={isRegister ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={inputCls}
          aria-invalid={fields.password ? true : undefined}
          aria-describedby={isRegister ? "password-hint" : undefined}
        />
        {isRegister && (
          <span id="password-hint" className="mt-1 block text-xs text-slate-500">
            至少 8 碼，不能全是數字。
          </span>
        )}
        {fieldError("password")}
      </label>
      {error && (
        <p role="alert" className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full rounded-md bg-teal-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-600"
      >
        {busy ? "處理中…" : isRegister ? "註冊並登入" : "登入"}
      </button>
      <p className="text-center text-sm text-slate-600">
        {isRegister ? "已經有帳號？" : "還沒有帳號？"}
        <Link
          href={`${isRegister ? "/login" : "/register"}${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`}
          className="text-teal-800 underline underline-offset-2"
        >
          {isRegister ? "登入" : "註冊"}
        </Link>
      </p>
    </form>
  );
}
