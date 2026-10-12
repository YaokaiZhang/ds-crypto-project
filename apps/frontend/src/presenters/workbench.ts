import type { AnalysisFamily } from '@/api/contracts';

export const workbenchLabels: Record<AnalysisFamily, { input: string; activity: string }> = {
  eth_scam: { input: 'Ethereum address', activity: 'Funds Flow & Activity' },
  token_scam: { input: 'ERC-20 token address', activity: 'Token & Pool Activity' },
};
