import type { Component } from 'vue';
import { Search, Wallet, Coins, Copy, ExternalLink, Network, RefreshCw, ZoomIn, ZoomOut, Maximize2, Pause, Play, X, ArrowRight } from 'lucide-vue-next';

export type IconName = 'search' | 'wallet' | 'token' | 'copy' | 'external-link' | 'graph' | 'refresh' | 'zoom-in' | 'zoom-out' | 'fit' | 'pause' | 'play' | 'close' | 'arrow-right';
// Replace this provider mapping without changing business components.
export const iconRegistry: Record<IconName, Component> = {
  search: Search, wallet: Wallet, token: Coins, copy: Copy,
  'external-link': ExternalLink, graph: Network, refresh: RefreshCw,
  'zoom-in': ZoomIn, 'zoom-out': ZoomOut, fit: Maximize2, pause: Pause, play: Play, close: X, 'arrow-right': ArrowRight,
};
