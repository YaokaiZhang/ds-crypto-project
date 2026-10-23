import { computed } from 'vue';
import { preferences } from '@/stores/preferences';

export function useTheme() {
  function setTheme(theme: 'light' | 'dark') {
    preferences.theme = theme;
    document.documentElement.dataset.theme = theme;
  }
  return { theme: computed(() => preferences.theme), setTheme };
}
