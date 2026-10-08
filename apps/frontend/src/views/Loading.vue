<template>
    <div class="loading-screen">
      <div class="wrap">
        <div class="round"></div>
        <div class="round"></div>
        <div class="round"></div>
        <div class="round"></div>
        <div class="round"></div>
        <div class="round"></div>
        <div class="round"></div>
      </div>
    </div>
  </template>
  
  <script setup>
  </script>
  
  <style scoped>
  .loading-screen {
    padding: 2rem;
    margin: 1.5rem;
    display: grid;
    justify-content: center;
    align-items: center;
    border-radius: 1rem;
    box-shadow: 0px 6px 12px rgba(0, 0, 0, 0.2);
    height: 60vh; /* 全屏显示 */
    background-color: rgba(0, 24, 72, 0.8); /* 与任务背景相同 */
  }
  
  .wrap {
    width: 75px;
    height: 75px;
    position: relative;
  }
  
  .round {
    position: absolute;
    width: 13px;
    height: 13px;
    border-radius: 50%;
    background-color: white; /* 修改为白色 */
    animation: circleRound 2.8s ease infinite;
    transform-origin: 50% 75px;
  }
  
  /* 各小球的大小及动画延迟 */
  .round:nth-child(2) {
    height: 12px;
    width: 12px;
    animation-delay: .2s;
  }
  
  .round:nth-child(3) {
    height: 11px;
    width: 11px;
    animation-delay: .4s;
  }
  
  .round:nth-child(4) {
    height: 10px;
    width: 10px;
    animation-delay: .6s;
  }
  
  .round:nth-child(5) {
    height: 9px;
    width: 9px;
    animation-delay: .8s;
  }
  
  .round:nth-child(6) {
    height: 8px;
    width: 8px;
    animation-delay: 1s;
  }
  
  .round:nth-child(7) {
    height: 7px;
    width: 7px;
    animation-delay: 1.2s;
  }
  
  @keyframes circleRound {
    to {
      transform: rotate(1turn);
    }
  }
  </style>
  