"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/format";
import type { CommentRow } from "@/lib/types";

import { useAuth } from "./auth-provider";

const MAX = 1000;

const STATUS_STYLE: Record<CommentRow["status"], string> = {
  pending: "bg-amber-50 text-amber-900 ring-amber-600/30",
  approved: "",
  rejected: "bg-ink-100 text-ink-700 ring-ink-500/30",
};

export function Comments({ ubn }: { ubn: string }) {
  const { user, loading: authLoading } = useAuth();
  const pathname = usePathname();
  const [rows, setRows] = useState<CommentRow[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");

  const [reloadKey, setReloadKey] = useState(0);

  const url = `/api/orgs/${ubn}/comments`;

  // 登入狀態一變就重抓：登入後要看得到自己審核中的留言
  useEffect(() => {
    if (authLoading) return;
    let cancelled = false;
    api<{ results: CommentRow[] }>(url)
      .then((r) => {
        if (cancelled) return;
        setRows(r.results);
        setLoadError("");
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [authLoading, user, url, reloadKey]);

  const retry = useCallback(() => {
    setLoadError("");
    setRows(null);
    setReloadKey((k) => k + 1);
  }, []);

  const trimmed = body.trim();
  const canSend = trimmed.length > 0 && trimmed.length <= MAX && !sending;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    setSending(true);
    setFormError("");
    setNotice("");
    try {
      const created = await api<CommentRow>(url, { method: "POST", body: { body: trimmed } });
      setRows((r) => [created, ...(r ?? [])]);
      setBody("");
      setNotice("已送出，管理員審核通過後會公開顯示。");
    } catch (err) {
      setFormError(err instanceof ApiError ? (err.fields.body?.[0] ?? err.message) : "送出失敗，請再試一次");
    } finally {
      setSending(false);
    }
  }

  async function remove(id: number) {
    if (!window.confirm("刪除後無法復原，確定要刪除這則留言嗎？")) return;
    try {
      await api(`/api/comments/${id}`, { method: "DELETE" });
      setRows((r) => (r ?? []).filter((c) => c.id !== id));
    } catch (err) {
      setFormError((err as Error).message);
    }
  }

  return (
    <section aria-labelledby="comments-title" className="space-y-4 border-t border-ink-200 pt-6">
      <h2 id="comments-title" className="font-display text-xl font-bold text-ink-900">
        留言
      </h2>

      {authLoading ? null : user ? (
        <form onSubmit={submit} className="space-y-2">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-ink-700">分享你的捐款經驗或疑問</span>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={3}
              maxLength={MAX}
              className="field-sizing-content min-h-24 w-full rounded-xl border border-ink-300 bg-white px-3 py-2 text-sm focus:border-brand-600 focus:outline-none"
              aria-describedby="comment-hint"
              aria-invalid={formError ? true : undefined}
            />
          </label>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span id="comment-hint" className="text-xs text-ink-500 tabular-nums">
              {trimmed.length} / {MAX}
            </span>
            <button
              type="submit"
              disabled={!canSend}
              className="rounded-xl bg-brand-700 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-800 disabled:cursor-not-allowed disabled:bg-ink-300 disabled:text-ink-600"
            >
              {sending ? "送出中…" : "送出留言"}
            </button>
          </div>
          {formError && (
            <p role="alert" className="text-sm text-red-800">
              {formError}
            </p>
          )}
          {notice && (
            <p role="status" className="text-sm text-emerald-800">
              {notice}
            </p>
          )}
        </form>
      ) : (
        <p className="rounded-xl bg-ink-100 px-4 py-3 text-sm text-ink-700">
          <Link href={`/login?next=${encodeURIComponent(pathname)}`} className="text-brand-800 underline underline-offset-2">
            登入
          </Link>
          後才能留言。
        </p>
      )}

      {loadError ? (
        <p role="alert" className="text-sm text-red-800">
          留言載入失敗：{loadError}{" "}
          <button type="button" onClick={retry} className="text-brand-800 underline underline-offset-2">
            重試
          </button>
        </p>
      ) : rows === null ? (
        <p className="text-sm text-ink-500">留言載入中…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-ink-600">還沒有留言。</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((c) => (
            <li key={c.id} className="surface p-4">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold text-ink-900">{c.author_name}</span>
                <span className="text-xs text-ink-500 tabular-nums">{formatDateTime(c.created_at)}</span>
                {c.status !== "approved" && (
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLE[c.status]}`}>
                    {c.status_label}
                  </span>
                )}
                {c.is_mine && (
                  <button
                    type="button"
                    onClick={() => remove(c.id)}
                    className="ml-auto rounded-full px-2 py-1 text-xs text-red-800 hover:bg-red-50"
                  >
                    刪除
                  </button>
                )}
              </div>
              <p className="mt-2 text-sm break-words whitespace-pre-line text-ink-800">{c.body}</p>
              {c.status === "rejected" && c.reject_reason && (
                <p className="mt-2 text-xs text-ink-600">未通過原因：{c.reject_reason}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
