<template>
  <!-- 添加条件渲染，当 showLoading 为 true 时，加载 Loading 组件 -->
  <div v-if="!showLoading" class="Heading-input">
    <section class="screening-header">
      <h1>Real-Time Data</h1>
      <h2>TrxLLM: 区块链风险检测系统</h2>
      <p>安全的、用户驱动的检测平台</p>
      <div class="input-section">
        <select v-model="selectedNetwork">
          <option value="Ethereum">Ethereum</option>
          <option value="Bitcoin">Bitcoin</option>
          <option value="Polkadot">Polkadot</option>
        </select>
        <!-- 按钮点击后调用 startLoading 显示加载动画 -->
        <button @click="startLoading">获取实时数据</button>
      </div>
    </section>
  </div>

  <!-- 加载动画，当 showLoading 为 true 时显示 Loading 组件 -->
  <Loading v-else />
  
  <section v-if="!showLoading" class="trade-task">
    <h3>实时数据检测任务：</h3>
    <p>
      该系统旨在实时监控和分析区块链交易，以识别和检测多种潜在风险，确保区块链生态系统的安全性。系统能够检测以下几种风险标签：钓鱼活动，识别实时进行的钓鱼攻击；恶意合约创建，发现正在部署的恶意智能合约；黑名单疑点，检测与已知黑名单地址相关的实时交易；窃取攻击活动，识别正在进行的资金窃取行为；蜜罐活动，检测诱骗用户资金的实时蜜罐交易。此外，系统还能标识无风险的安全交易，帮助用户及时识别和避免潜在的危险交易。
    </p>
  </section>
</template>

<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router'; // 导入 useRouter
import Loading from '@/views/Loading.vue'; // 引入加载动画组件

const router = useRouter(); // 创建路由对象
const selectedNetwork = ref('Ethereum');
const transactionHash = ref('');
const showDropdown = ref(false);

// 控制页面加载动画的显示与隐藏
const showLoading = ref(false);

const predictRisk = () => {
  // 模拟的交易预测函数
  alert(`正在预测 ${selectedNetwork.value} 网络下的交易哈希: ${transactionHash.value}`);
};

// 选择下拉菜单中的选项时，填充输入框
const selectOption = (hash) => {
  transactionHash.value = hash;
  showDropdown.value = false; // 选择后隐藏下拉菜单
};

// 隐藏下拉菜单
const hideDropdownMenu = () => {
  setTimeout(() => {
    showDropdown.value = false;
  }, 200); // 延迟以便点击选项时能触发
};

// 点击按钮后启动加载动画并根据 Hash 值跳转到不同的页面
const startLoading = () => {
  showLoading.value = true; // 显示加载动画
  setTimeout(() => {
      router.push('/explorer'); 
  }, 5000); // 5 秒后跳转
};
</script>

<style scoped>
/* 现有样式保持不变 */
.Heading-input {
}

.screening-header {
  background-color: rgba(0, 20, 72, 0.501);
  padding: 2rem;
  margin: 1.5rem;
  border-radius: 1rem;
  margin-bottom: 2rem;
  text-align: center;
  box-shadow: 0px 6px 12px rgba(0, 0, 0, 0.2);
}

.screening-header h1 {
  font-size: 2.5rem;
  margin-bottom: 0.5rem;
  color: #64d3ff;
}

.screening-header h2 {
  font-size: 1.5rem;
  margin-bottom: 1rem;
}

.screening-header p {
  font-size: 1.2rem;
  margin-bottom: 1.5rem;
}

.input-section {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
}

.input-section select,
.input-section input {
  padding: 0.5rem;
  border-radius: 0.5rem;
  border: 1px solid #ddd;
  background-color: #fff;
  color: #000;
  font-size: 1rem;
}

.input-section button {
  padding: 0.75rem 1.5rem;
  background-color: #1e90ff;
  border: none;
  border-radius: 0.5rem;
  color: #fff;
  font-size: 1rem;
  cursor: pointer;
  transition: background-color 0.3s ease;
}

.input-section button:hover {
  background-color: #4682b4;
}

.trade-task {
  margin: 1.5rem;
  background-color: rgba(0, 24, 72, 0.8);
  padding: 2rem;
  border-radius: 1rem;
  box-shadow: 0px 6px 12px rgba(0, 0, 0, 0.2);
  color: white;
}

.trade-task h3 {
  font-size: 1.8rem;
  color: #64d3ff;
  margin-bottom: 1rem;
}

.trade-task p {
  font-size: 1.1rem;
  line-height: 1.5;
}

.input-dropdown {
  position: relative;
}

.input-dropdown ul {
  position: absolute;
  top: 100%;
  left: 0;
  width: 100%;
  background-color: white;
  border: 1px solid #ddd;
  border-radius: 0.5rem;
  list-style: none;
  padding: 0;
  margin: 0.5rem 0 0 0;
  z-index: 10;
  overflow: hidden;
}

.input-dropdown ul li {
  padding: 0.5rem;
  cursor: pointer;
  color: #000;
  overflow: hidden;
}

.input-dropdown ul li:hover {
  background-color: #f0f0f0;
}
</style>
