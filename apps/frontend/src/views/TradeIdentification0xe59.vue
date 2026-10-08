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
      :r="node.central ? 17 : 13"
      :fill="node.fill ? node.fill : (node.central ? '#FFA500' : '#4FD1C5')"
      @mouseover="node.id === 1 ? showTooltip(node, $event) : null"
      @mouseleave="node.id === 1 ? hideTooltip() : null" 
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
  <div v-if="tooltipVisible" class="tooltip" :style="{ top: tooltipY + 'px', left: tooltipX + 'px' }">
          <div class="tooltip-content">
          <div>Node: {{ tooltipNode.id }}</div>
          <div>(UTC) 2024/09/11 00:04:11</div>
          <div>Hash: 0xc2b3...89ad0f</div>
          <div>13,944.236104 ETH</div>
          <div>Gas: 21000</div>
          <div>23.321585973 Gwei</div>
          <div class="alert-text">Alert</div>
        </div>
        </div>
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
              <img src="/public/icon/alert.png" alt="Alert" />
              涉及钓鱼活动
            </h3>
            <p class="risk-description">检测到可能的钓鱼相关行为，建议进一步调查</p>
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
            <span>20727786</span>
          </div>
          <div class="info-item">
            <span>Time:</span>
            <span>(UTC) 2024/09/11 13:52:11</span>
          </div>
          <div class="info-item">
            <span>From:</span>
            <span>0xceb69f6342ece283b2f5c9088ff249b5d0ae66ea</span>
          </div>
          <div class="info-item">
            <span>To:</span>
            <span>0xb4b163118db61a69e34c369c9a71e31bd58a08f7</span>
          </div>
          <div class="info-item">
            <span>Value:</span>
            <span>7,691.96753579562698125 ETH</span>
          </div>
          <div class="info-item">
            <span>Gas:</span>
            <span>21,000</span>
          </div>
          <div class="info-item">
            <span>Gas Price:</span>
            <span>3.984460778 Gwei</span>
          </div>
        </div>
        <div class="grid-item hash">
          <span>tr_hash: 0xe59fc2b3b41ed09821193b7fa7b4897e138cc2c6b3ed4f89ad0f79bb3e09b6d2</span>
          <span> &nbsp&nbsp| &nbsp检测结果：<img src="/public/icon/alert.png" alt="Alert" class="inline-icon" /> 风险项 1</span>
        </div>
      </div>
    </div>
  </template>
  
  <script setup>
import { ref } from 'vue';

const isAnimating = ref(false);
const elements = ref({ nodes: [], edges: [] });
const tooltipVisible = ref(false);
const tooltipNode = ref(null);
const tooltipX = ref(0);
const tooltipY = ref(0);

function showTooltip(node, event) {
  tooltipNode.value = node;
  tooltipVisible.value = true;
  tooltipX.value = event.clientX;
  tooltipY.value = event.clientY;
}

function hideTooltip() {
  tooltipVisible.value = false;
}

const graphData = {
  nodes: [
    { id: 0, x: 200, y: 100, central: true },
    { id: 1, x: 200, y: 200, fill: "red" },
    { id: 2, x: 300, y: 150 },
    { id: 3, x: 100, y: 150 },
    { id: 4, x: 250, y: 50 },
    { id: 5, x: 350, y: 50 },
    { id: 6, x: 50, y: 50 },
    { id: 8, x: 150, y: 250 },  // 改为节点 8 原来的位置
    { id: 7, x: 200, y: 300, central: true },  // 改为节点 7 原来的位置
    { id: 9, x: 250, y: 250 },
    { id: 10, x: 100, y: 350 },
    { id: 11, x: 300, y: 350 },
    { id: 12, x: 200, y: 400 },
  ],
  edges: [
    { source: 0, target: 1 },
    { source: 0, target: 2 },
    { source: 0, target: 3 },
    { source: 0, target: 4 },
    { source: 0, target: 5 },
    { source: 0, target: 6 },
    { source: 1, target: 7 },   // 连接到节点 7
    { source: 7, target: 8 },   // 连接节点 7 和 8
    { source: 7, target: 9 },
    { source: 7, target: 10 },
    { source: 7, target: 11 },
    { source: 7, target: 12 },
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
              if (nodeIndex !== -1) {
                elements.value.nodes[nodeIndex] = {
                  ...elements.value.nodes[nodeIndex],
                  fill: "red", // 变为红色
                };
              }
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

.tooltip {
  position: absolute;
  background-color: rgba(0, 0, 0, 0.8);
  padding: 10px;
  border-radius: 8px;
  color: white;
  font-size: 12px; /* 统一字体大小 */
  text-align: left; /* 左对齐 */
  z-index: 9999; /* 确保它在最上层 */
  box-shadow: 0px 4px 8px rgba(0, 0, 0, 0.2);
  pointer-events: none; /* 防止悬浮窗干扰鼠标交互 */
}

.tooltip-content div {
  margin-bottom: 5px; /* 保证每行之间的间距 */
}

.tooltip-content .alert-text {
  color: red; /* 保持 Alert 文本的红色 */
}

@keyframes draw {
  to {
    stroke-dashoffset: 0;
  }
}
  </style>