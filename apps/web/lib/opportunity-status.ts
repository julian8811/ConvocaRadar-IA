/** Deadline always wins over a stale stored status (e.g. Bancóldex still saying Abierto). */
export function liveOpportunityStatus(
  status: string,
  closeDate: string | null | undefined,
): string {
  if (!closeDate) return status;
  const close = new Date(closeDate);
  if (Number.isNaN(close.getTime())) return status;
  const now = new Date();
  const closeUtc = Date.UTC(close.getUTCFullYear(), close.getUTCMonth(), close.getUTCDate());
  const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  if (closeUtc < todayUtc) return "closed";
  return status;
}
