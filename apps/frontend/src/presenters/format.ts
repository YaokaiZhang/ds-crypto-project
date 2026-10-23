export function formatScore(score: number | null): string {
  return score === null ? '—' : score.toFixed(3);
}

export function shortenAddress(address: string): string {
  return address.length > 14 ? `${address.slice(0, 6)}…${address.slice(-4)}` : address;
}

/** Decimal string arithmetic preserves wei precision without floating-point rounding. */
export function formatWei(value: string): string {
  if (!/^\d+$/.test(value)) return 'Unavailable';
  const digits = value.replace(/^0+(?=\d)/, '').padStart(19, '0');
  const whole = digits.slice(0, -18);
  const fraction = digits.slice(-18).replace(/0+$/, '');
  return fraction ? `${whole}.${fraction}` : whole;
}

export function formatUtc(value: string | null): string {
  if (!value || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return 'Unavailable';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC') : 'Unavailable';
}

export function formatUnits(value: string, decimals: number): string {
  if (!/^\d+$/.test(value) || !Number.isInteger(decimals) || decimals < 0 || decimals > 36) return 'Unavailable';
  const digits = value.replace(/^0+(?=\d)/, '').padStart(decimals + 1, '0');
  if (decimals === 0) return digits;
  const fraction = digits.slice(-decimals).replace(/0+$/, '');
  return fraction ? `${digits.slice(0, -decimals)}.${fraction}` : digits.slice(0, -decimals);
}
