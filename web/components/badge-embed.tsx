"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { SITE_URL } from "@/lib/level-guide";

/** 揭露徽章的三種嵌入程式碼（LK-42）：網頁 HTML、Markdown、只要圖片網址；各一顆複製鈕 */
export function BadgeEmbed({ ubn, orgName }: { ubn: string; orgName: string }) {
  // 沒設正式網址時用目前網址的來源（伺服器端先空著，進瀏覽器再補）
  const origin = useSyncExternalStore(
    noopSubscribe,
    () => SITE_URL || window.location.origin,
    () => SITE_URL,
  );

  const page = `${origin}/orgs/${ubn}`;
  const img = `${origin}/api/orgs/${ubn}/badge.svg`;
  const alt = `${orgName}在 NPOFile 的揭露層級`;
  const codes = [
    { key: "html", label: "網頁（HTML）", hint: "貼進官網的 HTML 區塊", code: `<a href="${page}"><img src="${img}" alt="${alt}" height="20"></a>` },
    { key: "md", label: "Markdown", hint: "GitHub、Notion、部落格", code: `[![${alt}](${img})](${page})` },
    { key: "url", label: "圖片網址", hint: "Google 協作平台、電子報等只能貼圖片網址的地方，記得把圖片連到組織頁", code: img },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-xl bg-ink-50 px-4 py-5">
        {/* 預覽直接載真的徽章網址：看到的就是別人看到的 */}
        {origin && (
          <a href={page}>
            {/* eslint-disable-next-line @next/next/no-img-element -- SVG 徽章是後端即時產生的，不走 next/image */}
            <img src={img} alt={alt} height={20} className="h-5 w-auto" />
          </a>
        )}
      </div>
      <ul className="space-y-3">
        {codes.map((c) => (
          <li key={c.key}>
            <CodeRow label={c.label} hint={c.hint} code={origin ? c.code : "載入中…"} disabled={!origin} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function noopSubscribe() {
  return () => {};
}

function CodeRow({ label, hint, code, disabled }: { label: string; hint: string; code: string; disabled: boolean }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const t = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(t);
  }, [state]);

  const codeRef = useRef<HTMLElement>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setState("copied");
      return;
    } catch {
      // 剪貼簿權限被擋（舊瀏覽器、內嵌頁面）：選取文字再用舊做法複製；還是不行就留著選取，讓人自己按 Ctrl+C
    }
    const el = codeRef.current;
    const sel = window.getSelection();
    if (el && sel) {
      const range = document.createRange();
      range.selectNodeContents(el);
      sel.removeAllRanges();
      sel.addRange(range);
    }
    setState(document.execCommand?.("copy") ? "copied" : "failed");
  }

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-ink-900">
          {label}
          <span className="ml-2 font-normal text-ink-600">{hint}</span>
        </p>
      </div>
      <div className="mt-1.5 flex items-stretch gap-2">
        <code ref={codeRef} className="min-w-0 flex-1 overflow-x-auto rounded-lg bg-white px-3 py-2 font-mono text-xs leading-5 whitespace-nowrap text-ink-800 ring-1 ring-ink-200">
          {code}
        </code>
        <button
          type="button"
          onClick={copy}
          disabled={disabled}
          className="min-h-11 shrink-0 rounded-lg bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800 disabled:opacity-50"
          aria-live="polite"
        >
          {state === "copied" ? "已複製" : state === "failed" ? "已選取，請按 Ctrl+C" : "複製"}
        </button>
      </div>
    </div>
  );
}
