<template>
    <div class="dashboard">
      <div class="grid-container">
        <div class="grid-item graph">
          <!-- 左侧留空,用于未来的图表实现 -->
          <svg width="100%" height=80vh viewBox="0 0 400 500" style="position: relative; display: block;">
    <!-- 渲染边 -->
    <g v-for="(edge, index) in elements.edges" :key="'edge-' + index">
      <line
        :x1="getNode(edge.source).x"
        :y1="getNode(edge.source).y"
        :x2="getNode(edge.target).x"
        :y2="getNode(edge.target).y"
        stroke="rgba(255, 255, 255, 0.6)"
        stroke-width="2"
        class="draw-line"
      />
    </g>

    <!-- 渲染节点 -->
    <transition-group name="fade" tag="g">
  <g v-for="(node, index) in elements.nodes" :key="'node-' + node.id">
    <circle
      :cx="node.x"
      :cy="node.y"
      :r="node.central ? 13 : 10"
      :fill="node.fill ? node.fill : (node.central ? '#FFA500' : '#4FD1C5')" 
    />
    <!-- 在节点旁边添加数字 -->
    <text
      :x="node.x"
      :y="node.y"
      dy="0.35em"
      text-anchor="middle"
      fill="white"
      font-size="12"
      font-family="Arial"
    >
      {{ node.id }}
    </text>
  </g>
</transition-group>


  </svg>
          <button
            class="animation-toggle-button"
            @click="handleAnimationToggle"
            >
            {{ isAnimating ? '清空图形' : '生成图形' }}
        </button>
        </div>
        <div class="grid-item risk-assessment">
          <div class="risk-item">
            <h3 class="risk-heading">
              <img src="/public/icon/safe.png" alt="Safe" />
              未涉及钓鱼活动
            </h3>
            <p class="risk-description">未检测到可能的钓鱼相关行为，建议进一步调查</p>
          </div>
          <div class="risk-item">
            <h3 class="risk-heading">
              <img src="/public/icon/safe.png" alt="Safe" />
              未涉及恶意合约创建活动
            </h3>
            <p class="risk-description">未发现创建恶意合约的迹象，交易安全</p>
          </div>
          <div class="risk-item">
            <h3 class="risk-heading">
              <img src="/public/icon/safe.png" alt="Safe" />
              未涉及黑名单疑点
            </h3>
            <p class="risk-description">交易地址未出现在已知的可疑地址列表中</p>
          </div>
          <div class="risk-item">
            <h3 class="risk-heading">
              <img src="/public/icon/safe.png" alt="Safe" />
              未涉及窃取攻击活动
            </h3>
            <p class="risk-description">未检测到与窃取攻击相关的模式</p>
          </div>
          <div class="risk-item">
            <h3 class="risk-heading">
              <img src="/public/icon/safe.png" alt="Safe" />
              未涉及蜜罐活动
            </h3>
            <p class="risk-description">未检测到与蜜罐活动相关的特征</p>
          </div>
        </div>
        <div class="grid-item transaction-info">
          <h2>交易信息</h2>
          <div class="info-item">
            <span>Block Number:</span>
            <span>20728408</span>
          </div>
          <div class="info-item">
            <span>Time:</span>
            <span>(UTC) 2024/09/11 15:57:23</span>
          </div>
          <div class="info-item">
            <span>From:</span>
            <span>0x1417287c5237418d47a3c30b7e89d536028b8b1b</span>
          </div>
          <div class="info-item">
            <span>To:</span>
            <span>0xceb69f6342ece283b2f5c9088ff249b5d0ae66ea</span>
          </div>
          <div class="info-item">
            <span>Value:</span>
            <span>19,902.0030301377680492 ETH</span>
          </div>
          <div class="info-item">
            <span>Gas:</span>
            <span>21,000</span>
          </div>
          <div class="info-item">
            <span>Gas Price:</span>
            <span>4.054752255 Gwei</span>
          </div>
        </div>
        <div class="grid-item hash">
          <span>tr_hash: 0xdbc3d5fce7d63844e1bf0584738ad43b8bf55bb2b8ee28ad0b1853c5cab4795d</span>
          <span> &nbsp&nbsp| &nbsp检测结果：<img src="/public/icon/safe.png" alt="Safe" class="inline-icon" /> 风险项 0</span>
        </div>
      </div>
    </div>
  </template>
  
  <script setup>
import { ref } from 'vue';

const isAnimating = ref(false);
const elements = ref({ nodes: [], edges: [] });

const graphData = {
  nodes: [
    { id: 0, x: 250, y: 260, central: true },
    { id: 1, x: 220, y: 200 },
    { id: 2, x: 320, y: 290 },
    { id: 3, x: 260, y: 330 },
    { id: 4, x: 190, y: 160 },
    { id: 7, x: 270, y: 400, central: true },
    { id: 5, x: 160, y: 120, central: true },
    { id: 6, x: 100, y: 120 },
    { id: 8, x: 230, y: 90 },
    { id: 9, x: 170, y: 40 },
    { id: 10, x: 120, y: 30 },
    { id: 11, x: 280, y: 450},
    { id: 12, x: 200, y: 400},
    { id: 13, x: 330, y: 400},
  ],
  edges: [
    { source: 0, target: 1 },
    { source: 0, target: 2 },
    { source: 0, target: 3 },
    { source: 1, target: 4 },
    { source: 4, target: 5 },
    { source: 5, target: 6 },
    { source: 3, target: 7 },
    { source: 5, target: 8 },
    { source: 5, target: 9 },
    { source: 5, target: 10},
    { source: 7, target: 11},
    { source: 7, target: 12},
    { source: 7, target: 13},
  ],
};



const handleAnimationToggle = () => {
  if (!isAnimating.value) {
    elements.value = { nodes: [graphData.nodes[0]], edges: [] };

    graphData.edges.forEach((edge, index) => {
      setTimeout(() => {
        elements.value.edges.push(edge);

        const targetNode = graphData.nodes.find(
          (node) => node.id === edge.target
        );

        setTimeout(() => {
          elements.value.nodes.push(targetNode);

          // 最后一个节点生成后再变红
          if (index === graphData.edges.length - 1) {
            setTimeout(() => {
              const nodeIndex = elements.value.nodes.findIndex(
                (node) => node.id === 1
              );
            }, 600); // 增加延时，确保所有动画完成
          }
        }, 300);
      }, index * 600);
    });
  } else {
    elements.value = { nodes: [], edges: [] };
  }
  isAnimating.value = !isAnimating.value;
};


const getNode = (id) => {
  return graphData.nodes.find((node) => node.id === id);
};

  </script>
  
  <style scoped>
  .dashboard {
    padding: 1rem;
  }
  
  .grid-container {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: auto auto auto;
    gap: 1rem;
  }
  
  .grid-item {
    background-color: rgba(0, 24, 72, 0.8);
    border-radius: 1rem;
    box-shadow: 0px 6px 12px rgba(0, 0, 0, 0.2);
    padding: 1rem;
    color: white;
  }
  
  .graph {
    grid-row: span 2;
    background-color: rgba(0, 20, 72, 0.501);
    position: relative;
    display: flex;
    justify-content: center;
    align-items: center;
    flex-direction: column;

  }
  
  .risk-item {
    margin-bottom: 1rem;
  }
  
  .risk-heading {
    display: flex;
    align-items: center;
    font-size: 1.2rem;
    margin: 0 0 0.5rem 0;
  }
  
  .risk-heading img {
    width: 32px;
    height: 32px;
    margin-right: 0.75rem;
  }
  
  .risk-description {
    margin: 0 0 0 2.75rem;
    font-size: 0.9rem;
    color: #cccccc;
    text-align: left;
  }
  
  .transaction-info h2 {
    margin-top: 0;
  }
  
  .info-item {
    display: flex;
    align-items: center;
    margin-bottom: 0.5rem;
  }
  
  .info-item span:first-child {
    font-weight: bold;
    margin-right: 0.5rem;
  }
  
  .hash {
    grid-column: span 2;
    display: flex;
    justify-content: center;
    align-items: center;
  }
  
  .inline-icon {
    width: 20px;
    height: 20px;
    vertical-align: middle;
    margin: 0 5px;
  }

  .animation-toggle-button {
  background-color: rgba(255, 255, 255, 0.2);
  color: white;
  font-weight: 600;
  padding: 0.5rem 1.5rem;
  border-radius: 9999px;
  transition: all 0.3s ease-in-out;
  transform: scale(1);
  margin-top: 1rem; /* 保证按钮距离图形有一定的间距 */
  outline: none;
  box-shadow: 0px 6px 12px rgba(0, 0, 0, 0.2);
}


.animation-toggle-button:hover {
  background-color: rgba(255, 255, 255, 0.3);
  transform: scale(1.05);
}

.animation-toggle-button:focus {
  outline: none;
  box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.5);
}

/* 节点动画 */
/* 取消缩放效果，节点直接生成 */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.5s;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
.fade-enter-to, .fade-leave-from {
  opacity: 1;
}


/* 线条绘制动画 */
.draw-line {
  stroke-dasharray: 200;
  stroke-dashoffset: 200;
  animation: draw 0.5s forwards;
}

@keyframes draw {
  to {
    stroke-dashoffset: 0;
  }
}
  </style>