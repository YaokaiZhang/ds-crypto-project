<template>
  <footer>
    <div class="logo">TrxLLM</div>
    <div class="contact">
      <!-- 透明按钮覆盖GitHub图标，确保在点击时跳转 -->
      <a href="https://github.com/whusjj/blockchain-code" class="github-link" target="_blank" aria-label="Github Link">
        <img src="/public/icon/github.png" alt="Github" />
      </a>

      <!-- 其他联系方式图标 -->
      <a href="#">
        <img src="/public/icon/gmail.png" alt="Email" />
      </a>
      <a href="#">
        <img src="/public/icon/hp.png" alt="Phone" />
      </a>
    </div>
  </footer>
</template>

<script setup>
</script>

<style scoped>
footer {
  background-color: rgba(0, 24, 72, 0.8);
  backdrop-filter: blur(8px);
  padding: 1.5rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo {
  font-size: 2rem;
  font-weight: bold;
  color: #64d3ff;
}

.contact {
  display: flex;
  align-items: center;
}

.contact a {
  margin-left: 1rem;
  position: relative; /* 新增：确保其子元素按需定位 */
  transition: transform 0.2s ease;
}

.contact img {
  width: 30px;
  height: 30px;
  transition: transform 0.3s ease, filter 0.3s ease;
}

.contact a:hover img {
  transform: scale(1.1);
  filter: brightness(1.2);
}

/* 确保透明按钮无障碍，覆盖GitHub图标 */
.github-link {
  display: inline-block;
  position: relative;
  cursor: pointer;
}
</style>