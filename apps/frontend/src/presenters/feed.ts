import type { FeedMeta, FeedSnapshot, FeedTransaction } from '@/api/contracts';

const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid feed response');
  return value as Record<string, unknown>;
};
const integer = (value: unknown) => Number.isSafeInteger(value) && (value as number) >= 0;
const decimal = (value: unknown) => typeof value === 'string' && /^\d+$/.test(value);
const date = (value: unknown) => typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const hex = (value: unknown, size: number) => typeof value === 'string' && new RegExp(`^0x[0-9a-f]{${size}}$`, 'i').test(value);

export function readFeedTransaction(value: unknown): FeedTransaction {
  const row = object(value);
  if (!hex(row.hash, 64) || !hex(row.block_hash, 64) || !hex(row.from_address, 40) ||
      (row.to_address !== null && !hex(row.to_address, 40)) || !integer(row.block_number) ||
      !integer(row.transaction_index) || !date(row.block_time) || !decimal(row.value_wei) || !decimal(row.gas_limit) ||
      !['gas_used', 'effective_gas_price_wei', 'execution_fee_wei'].every(key => row[key] === null || decimal(row[key])) ||
      ![null, 'success', 'failed'].includes(row.status as string | null)) throw new Error('Invalid feed transaction');
  return row as unknown as FeedTransaction;
}
export function readFeedMeta(value: unknown): FeedMeta {
  const meta = object(value);
  if (!['connecting', 'live', 'degraded', 'stale', 'recovering'].includes(meta.status as string) || !integer(meta.sequence) ||
      !['updated_at', 'checked_at', 'head_time', 'last_gap_at'].every(key => meta[key] === null || date(meta[key])) ||
      (meta.head_block !== null && !integer(meta.head_block)) || typeof meta.source !== 'string' ||
      (meta.message !== null && typeof meta.message !== 'string')) throw new Error('Invalid feed state');
  const quote = meta.usd_quote ?? null;
  if (quote !== null) {
    const price = object(quote);
    if (typeof price.price !== 'string' || price.price.length > 40 || !/^\d+(\.\d+)?$/.test(price.price) ||
        !/[1-9]/.test(price.price) || !date(price.fetched_at) || typeof price.source !== 'string') throw new Error('Invalid ETH/USD quote');
  }
  return { ...meta, usd_quote: quote } as unknown as FeedMeta;
}
export function readFeedSnapshot(value: unknown): FeedSnapshot {
  const data = object(value); const meta = readFeedMeta(data);
  if (!Array.isArray(data.transactions) || data.transactions.length > 100) throw new Error('Invalid feed snapshot');
  const rows = data.transactions.map(readFeedTransaction);
  if (new Set(rows.map(row => row.hash)).size !== rows.length) throw new Error('Duplicate feed transaction');
  return { ...meta, transactions: rows.filter(row => BigInt(row.value_wei) > 0n).slice(0, 30) };
}
export function appendFeedTransaction(current: FeedSnapshot, value: unknown): FeedSnapshot {
  const data = object(value); const meta = readFeedMeta(data.meta); const row = readFeedTransaction(data.transaction);
  if (meta.sequence <= current.sequence) return current;
  if (BigInt(row.value_wei) === 0n) return { ...current, ...meta };
  return { ...meta, transactions: [row, ...current.transactions.filter(item => item.hash !== row.hash)].slice(0, 30) };
}

/** Exact Wei × decimal quote, rounded only at the display's cent boundary. */
export function formatFeedUsd(wei: string, price: string): string {
  if (!/^\d+$/.test(wei) || !/^\d+(\.\d+)?$/.test(price) || price.length > 40) return 'Unavailable';
  const [whole, fraction = ''] = price.split('.');
  const numerator = BigInt(wei) * BigInt(whole + fraction);
  const divisor = 10n ** BigInt(18 + fraction.length);
  const cents = (numerator * 100n + divisor / 2n) / divisor;
  if (numerator > 0n && cents === 0n) return '<$0.01';
  const dollars = (cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `$${dollars}.${(cents % 100n).toString().padStart(2, '0')}`;
}
