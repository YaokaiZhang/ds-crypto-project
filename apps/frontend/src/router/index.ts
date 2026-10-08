import { createRouter, createWebHistory } from 'vue-router';
import Home from '@/views/Home.vue';
import TradeIdentification from '@/views/TradeIdentification.vue'
import Loading from '@/views/Loading.vue'; // 加载页面
import TradeIdentification0xe59 from '@/views/TradeIdentification0xe59.vue';
import TradeIdentification0xdbc from '@/views/TradeIdentification0xdbc.vue';
import AddressDetection from '@/views/AddressDetection.vue';
import AddressDetection0x2da from '@/views/AddressDetection0x2da.vue';
import Explorer from '@/views/Explorer.vue';
import RealTimeData from '@/views/RealTimeData.vue'

const routes = [
  { path: '/', name: 'Home', component: Home },
  { path: '/trade-identification', name: 'TradeIdentification', component: TradeIdentification },
  { path: '/loading', name: 'Loading', component: Loading }, // 新增加载动画页面
  { path: '/trade-identification-0xe59', name: 'TradeIdentification0xe59', component: TradeIdentification0xe59 },
  { path: '/trade-identification-0xdbc', name: 'TradeIdentification0xdbc', component: TradeIdentification0xdbc },
  { path: '/address-detection', name: 'AddressDetection', component: AddressDetection },
  { path: '/address-detection-0x2da', name: 'AddressDetection0x2da', component: AddressDetection0x2da },
  { path: '/explorer', name: 'Explorer', component: Explorer },
  { path: '/real-time-data', name: 'RealTimeData', component: RealTimeData },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
