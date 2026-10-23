import { createRouter, createWebHistory } from 'vue-router';

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('@/pages/HomePage.vue') },
    { path: '/forecast', name: 'forecast', component: () => import('@/pages/ForecastPage.vue') },
    { path: '/eth-scam', name: 'eth-scam', component: () => import('@/pages/ETHScamPage.vue') },
    { path: '/token-scam', name: 'token-scam', component: () => import('@/pages/TokenScamPage.vue') },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/pages/NotFoundPage.vue') },
  ],
});
