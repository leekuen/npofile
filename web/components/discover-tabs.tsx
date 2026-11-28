"use client";

import { type KeyboardEvent, type ReactNode, useId, useRef, useState } from "react";

/** 首頁探索區的分頁列：長相沿用組織頁的分頁（底線＋粗體），可用左右方向鍵切換。 */
export function DiscoverTabs({ tabs }: { tabs: { key: string; label: string; panel: ReactNode }[] }) {
  const [active, setActive] = useState(0);
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKey(e: KeyboardEvent) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = (active + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    setActive(next);
    refs.current[next]?.focus();
  }

  return (
    <div>
      <div role="tablist" aria-label="探索" onKeyDown={onKey} className="-mx-1 mb-4 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-ink-200 px-1">
        {tabs.map((t, i) => (
          <button
            key={t.key}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${t.key}`}
            aria-selected={i === active}
            aria-controls={`${id}-panel-${t.key}`}
            tabIndex={i === active ? 0 : -1}
            onClick={() => setActive(i)}
            className={`-mb-px shrink-0 border-b-2 px-3 py-3 transition-colors duration-200 text-sm font-medium whitespace-nowrap ${
              i === active ? "border-brand-700 font-bold text-brand-900" : "border-transparent text-ink-600 hover:text-ink-900"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs.map((t, i) => (
        <div key={t.key} role="tabpanel" id={`${id}-panel-${t.key}`} aria-labelledby={`${id}-tab-${t.key}`} hidden={i !== active} className="animate-rise">
          {t.panel}
        </div>
      ))}
    </div>
  );
}
