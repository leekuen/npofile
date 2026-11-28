"use client";

import { useEffect } from "react";

/**
 * 從首頁卡片連到 `?tab=projects#p-<編號>` 時，把那一筆捲到眼前並框起來。
 * 站內換頁不會觸發瀏覽器的 :target，所以自己找、自己標（data-highlight）。
 */
export function HashHighlight() {
  useEffect(() => {
    function apply() {
      document.querySelectorAll("[data-highlight]").forEach((el) => el.removeAttribute("data-highlight"));
      const id = decodeURIComponent(window.location.hash.slice(1));
      const el = id ? document.getElementById(id) : null;
      if (!el) return;
      el.setAttribute("data-highlight", "");
      el.scrollIntoView({ block: "start" });
    }
    apply();
    window.addEventListener("hashchange", apply);
    return () => window.removeEventListener("hashchange", apply);
  }, []);
  return null;
}
