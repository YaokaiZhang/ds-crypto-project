import { createApp } from 'vue';
import App from './App.vue';
import router from './router';
import './design/themes/default.css';
import './design/tokens.css';
import './styles/base.css';

createApp(App).use(router).mount('#app');
