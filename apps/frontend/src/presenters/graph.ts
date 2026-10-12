import type { GraphView } from '@/api/contracts';
import type { ChartTheme } from '@/design/chartTheme';

// Implement against the selected graph library; retain the API GraphSample identity.
export interface GraphRenderer {
  mount(container: HTMLElement): void;
  update(graph: GraphView, theme: ChartTheme): void;
  dispose(): void;
}
