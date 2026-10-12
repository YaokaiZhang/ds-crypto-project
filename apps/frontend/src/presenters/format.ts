export function formatScore(score: number | null): string {
  return score === null ? '—' : score.toFixed(3);
}

export function shortenAddress(address: string): string {
  return address.length > 14 ? `${address.slice(0, 6)}…${address.slice(-4)}` : address;
}
