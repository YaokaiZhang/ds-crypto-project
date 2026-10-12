export interface ChartTheme {
  surface: string;
  text: string;
  border: string;
  accent: string;
}

export function resolveChartTheme(element: HTMLElement = document.documentElement): ChartTheme {
  const style = getComputedStyle(element);
  const token = (name: string) => style.getPropertyValue(name).trim();
  return { surface: token('--surface-panel'), text: token('--text-primary'), border: token('--border-default'), accent: token('--accent') };
}
