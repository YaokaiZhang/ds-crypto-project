import type { GraphView } from '@/api/contracts';
import type { ChartTheme } from '@/design/chartTheme';
import { createApp, h, shallowRef, type App } from 'vue';
import TransactionGraphCanvas from '@/components/analysis/TransactionGraphCanvas.vue';
import { readDisplayGraph, type DisplayGraph } from './graphDisplay';

// Renderer boundary retained for future canvas/WebGL engines.
export interface GraphRenderer {
  mount(container: HTMLElement): void;
  update(graph: GraphView, theme: ChartTheme): void;
  dispose(): void;
}

/** Mount a declarative SVG renderer behind the existing engine lifecycle. */
export function createGraphRenderer(): GraphRenderer {
  const graph = shallowRef<DisplayGraph | null>(null);
  let app: App | undefined;
  let container: HTMLElement | undefined;
  return {
    mount(element) {
      app?.unmount(); container = element;
      app = createApp({ render: () => graph.value ? h(TransactionGraphCanvas, { graph: graph.value }) : null });
      app.mount(element);
    },
    update(value, theme) {
      graph.value = readDisplayGraph(value);
      container?.style.setProperty('--graph-surface', theme.surface);
      container?.style.setProperty('--graph-text', theme.text);
      container?.style.setProperty('--graph-accent', theme.accent);
    },
    dispose() { app?.unmount(); app = undefined; container = undefined; graph.value = null; },
  };
}
