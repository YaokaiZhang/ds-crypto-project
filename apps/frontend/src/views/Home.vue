<template>
  <div>
    <Header />
    <main>
      <div class="description">
        <h2>TrxLLM</h2>
        <p>
          多维度综合评估交易和账户风险，通过机器学习和图神经网络技术，
          全面分析交易图中的节点和边信息，提供详细的风险分析报告和安全建议，
          支持系统的持续改进和优化。
        </p>
      </div>
      <div class="features">
        <Feature
          title="交易甄别"
          description="实时检测和识别异常交易行为，利用多维特征分析保障交易安全，防范欺诈和恶意行为。"
          :icon="Shield"
        />
        <Feature
          title="地址检测"
          description="分析区块链地址的历史行为和交易模式，评估风险等级，识别潜在威胁并提供预警。"
          :icon="UserCheck"     
        />
        <Feature
          title="实时数据"
          description="提供区块链交易的实时监控与数据分析，确保信息的及时性和准确性，支持实时决策。"
          :icon="BarChart2"
        />
      </div>
    </main>
  </div>
</template>

<script setup>

// 引入 Lucide 图标
import { Shield, UserCheck, Code, BarChart2 } from 'lucide-vue-next';
import Feature from '@/components/Feature.vue';
</script>

<style scoped>
/*
.description {
  background-color: rgba(0, 0, 0, 0.5);
  padding: 2rem;
  margin: 2rem;
  border-radius: 1rem;
  text-align: center;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  color: #fff;
}*/
.description {
  background-color: rgba(0, 24, 72, 0.7); 
  padding: 1.5rem; 
  margin: 2rem; 
  border-radius: 0.75rem; 
  text-align: left; 
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5); 
  color: #fff; 
}


.features {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 2rem;
  padding: 2rem;
}

@media (max-width: 768px) {
  .features {
    grid-template-columns: 1fr; /* 在小屏幕上单列显示 */
  }
}
</style>
