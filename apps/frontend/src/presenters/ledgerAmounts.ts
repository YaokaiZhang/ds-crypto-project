import type { LedgerRow } from '../api/contracts';
import { formatUnits } from './format';

export function ledgerAmounts(row: LedgerRow): { text: string; title: string }[] {
  const amounts: { text: string; title: string }[] = [];
  if (row.value_raw !== null && /^\d+$/.test(row.value_raw) && row.decimals !== null
      && (row.category !== 'external' || BigInt(row.value_raw) > 0n)) {
    const value = formatUnits(row.value_raw, row.decimals);
    if (value !== 'Unavailable') amounts.push({ text: `${value} ${row.asset || ''}`.trim(), title: row.category === 'token_transfer' ? row.emitter || row.asset || 'Token transfer amount.' : 'Native transaction value; excludes gas.' });
  }
  if (row.category === 'external' && row.status === 'success') {
    for (const amount of row.amounts || []) {
      const value = formatUnits(amount.raw, amount.decimals);
      if (value === 'Unavailable') continue;
      amounts.push({ text: `${value} ${amount.asset}${amount.direction ? ` (${amount.direction})` : ''}`,
        title: amount.contract_address || amount.asset });
    }
  }
  return amounts.length ? amounts : [{ text: 'Unknown', title: 'No asset amount identified in the available records.' }];
}
