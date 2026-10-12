import type { Component } from 'vue';
import { Search, Wallet, Coins, Copy, ExternalLink, Network, RefreshCw } from 'lucide-vue-next';

export type IconName = 'search' | 'wallet' | 'token' | 'copy' | 'external-link' | 'graph' | 'refresh';
// Replace this provider mapping without changing business components.
export const iconRegistry: Record<IconName, Component> = {
  search: Search, wallet: Wallet, token: Coins, copy: Copy,
  'external-link': ExternalLink, graph: Network, refresh: RefreshCw,
};
