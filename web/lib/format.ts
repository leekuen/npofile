const money = new Intl.NumberFormat("zh-TW");

export function formatMoney(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${money.format(value)} 元`;
}

/** 大金額的短寫法：1.2 億、3,691 萬（圖表軸、卡片摘要用；表格一律寫完整數字） */
export function formatCompact(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(abs >= 1e9 ? 0 : 1)} 億`;
  if (abs >= 1e4) return `${Math.round(v / 1e4).toLocaleString("zh-TW")} 萬`;
  return v.toLocaleString("zh-TW");
}

export function formatNumber(value: number): string {
  return money.format(value);
}

/** ISO 日期 → 民國日期（例：113/05/31），跟政府資料來源一致 */
export function formatRocDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${y - 1911}/${String(m).padStart(2, "0")}/${String(d).padStart(2, "0")}`;
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false }).slice(0, -3);
}
