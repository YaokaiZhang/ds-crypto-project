import { reactive } from 'vue';

// UI preferences only. Server results belong to their analysis ID.
export const preferences = reactive<{ theme: 'light' | 'dark'; feedPaused: boolean }>({
  theme: 'dark', feedPaused: false,
});
