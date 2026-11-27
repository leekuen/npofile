const money = new Intl.NumberFormat("zh-TW");

export function formatMoney(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${money.format(value)} 元`;
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
