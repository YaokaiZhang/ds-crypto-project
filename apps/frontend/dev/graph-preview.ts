// Separate Vite development entry. Never imported by the application router.
if (import.meta.env.DEV) {
  const [{ createApp }, { default: Preview }] = await Promise.all([import('vue'), import('./GraphPreview.vue')]);
  createApp(Preview).mount('#graph-preview');
}
