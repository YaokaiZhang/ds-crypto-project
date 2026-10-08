<template>
    <div class="container">
   <div class="header">
   <h2 class="title">Ethereum Blockchain Trade Info &nbsp &nbsp &nbsp &nbsp &nbsp &nbsp &nbsp &nbsp &nbspBlock Number: 19876365</h2>
   <button @click="updateData" :disabled="isLoading" class="update-button">
   <template v-if="isLoading">
   <span class="loading-icon">&#9696;</span>
    Updating...
   </template>
   <template v-else>
    Update Data
   </template>
   </button>
   </div>
   <div class="table-container">
   <table>
   <thead>
   <tr>
   <th>Transaction Hash</th>
   <th>From</th>  
   <th>To</th>
   <th>Detect</th>
   </tr>
   </thead>
   <tbody>
   <tr v-for="(item, index) in displayedData" :key="index" :class="{ 'even-row': index % 2 === 0 }">
   <td>
   <div class="truncate" :title="item.hash">{{ truncateHash(item.hash) }}</div>
   </td>
   <td>
   <div class="truncate" :title="item.from">{{ truncateHash(item.from) }}</div>  
   </td>
   <td>
   <div class="truncate" :title="item.to">{{ truncateHash(item.to) }}</div>
   </td>
   <td :class="item.detect === '危险' ? 'danger' : 'safe'">
    {{ item.detect }}
   </td>
   </tr>
   </tbody>
   </table>
   </div>
   </div>
   </template>
   
   <script setup>
   import { ref, computed } from 'vue';
   
   const initialData = [
  { hash: '0xa5554fdbac0d8fb69c56aaba53ec9f05f8387f7709533b40ff8ae1120d765ad2', from: '0x28c6c06298d514db089934071355e5743bf21d60', to: '0xf17aced3c7a8daa29ebb90db8d1b6efd8c364a18', detect: '安全' },
  { hash: '0xa1ca13518b3e37d7c41257ec37716f81ddeaa9f4daec884df1bb31a6bc4e6c7e', from: '0x41e3910651bcafb53feee98a164c19ced2bbd27e', to: '0x477b8d5ef7c2c42db84deb555419cd817c336b6f', detect: '安全' },
  { hash: '0x463fe4e29369403bf91f190b0ad73da29055ba13ddb7d24a2bee68127807c944', from: '0x1c68c3de2b02d9ae478d37c7e6c92a53ff01fc66', to: '0xa5995359b9941e060e366b4ee3ebb6a9f47649be', detect: '危险' },
  { hash: '0xb7554f96afc57daccfbcf27edbfc207ffcd9f52a9cedcf57fc1d152c3ed2f958', from: '0xbf94f0ac752c739f623c463b5210a7fb2cbb420b', to: '0x452a7bcd14fe5a37cdecd0925df824fd01562b86', detect: '安全' },
  { hash: '0x1cd4f3cb39a5bf5529ed3f912b4514ed49cf0bad1cc6e50589a33aa55924b0ca', from: '0x85464b207d7c1fce8da13d2f3d950c796e399a9c', to: '0x1c68c3de2b02d9ae478d37c7e6c92a53ff01fc66', detect: '安全' },
  { hash: '0xa08e5f1794d2b5d5655fd3f5de9a442b349cd8e12bf31467a377eb8ddd49a01e', from: '0x32d4703e5834f1b474b17dfdb0ac32cc22575145', to: '0xcffad3200574698b78f32232aa9d63eabd290703', detect: '安全' },
  { hash: '0x26dc67f904557e6f9d8e15d7765a2a0ae306521d6dc6b853ea4fb2a42fa1c909', from: '0x21a31ee1afc51d94c2efccaa2092ad1028285549', to: '0x32d4703e5834f1b474b17dfdb0ac32cc22575145', detect: '安全' },
  { hash: '0x1b52307bc103035cbc675e122492098cfd82213503a5fabb801928c0ad03ff3f', from: '0xfa6f469580b1caa4934817f6f8e6c0e1a94ff4e1', to: '0xfa6f469580b1caa4934817f6f8e6c0e1a94ff4e1', detect: '安全' },
  { hash: '0x771d5d5f3d5e3f5a5b2d8a2e95b4f4a4c5e1d3d5d23a1e5a5b2e8f4a4c5d1e3d', from: '0xa3f5d5f3a5e3d5a5b2a2e95e1f4a4b3a5e3d5f3a', to: '0xb2d8a2e95f4a4c5e1d3d5d23a1e5a5b2e8f4a4c5', detect: '安全' },
  { hash: '0xb1e5a5f2d8a2e93f4a4c5e1c3d5d21a1e5a2b2e8d4a4c3e1d3d2a2e95f4a4b3a', from: '0x5e3f5a5b3a2e95e4f4a4b3a2e1d3d5f3a5e3f5a5', to: '0xd23a1e5a4b2e8f2a4c5d1e3d5d23a2e95f4a4b3a', detect: '危险' },
  { hash: '0x5d23a1e4a5b2e85f4a4c5e2d3d5d13a1e5a4b2e8a4c5e2d3d5f2a1e95f4a4b3', from: '0xe95f4a4b5a2e95e2f4a4c5d2e3d5d21a1e5a4b2e', to: '0xf4a4c5e13d5d23a4e5a5b2e8a4c5d2e3d5f2a1e9', detect: '安全' },
  { hash: '0x3d5d23a2e5a5b14e8f4a4c2d1e3d5e3a1e5a4b2e5f4a4c5d2e3d2a1e95f4a4b3', from: '0x5f4a4b3a3e95f4a2c5d2e3d4d23a1e5a1b2e8f4a', to: '0x4c5d2e3d3d23a1e5a5b2e8f2a4c5d1e4d5f2a1e9', detect: '安全' },
  { hash: '0x2a1e5a4e2e8f4a3c5d2e3d4d23a1e5a5b2e8f4a1c5d2e3d5f2a3e95f4a4b3a2', from: '0xe95f4a4b4a2e95e3f4a4c5d1e3d5d23a2e5a5b2e', to: '0x8f4a4c5d3e3d5d22a1e5a4b3e8f4a4c2d2e3d5f2', detect: '安全' },
  { hash: '0x1e5a4b2e3f4a4c54d2e3d5d12a1e5a5b3e8f4a4c2d2e3d5f1a2e95e4f4a4b3a', from: '0xa1e95f4a3b3a2e954f4a4c5d2e4d5d23a1e2a5b2', to: '0xe8f4a4c5d2e3d5f21a1e5a4b2e8f4a4c3d2e3d5f', detect: '安全' },
  { hash: '0x4b2e8f4a2c5d2e34d5d23a1e5a5b2e8f3a4c5d2e4d5f2a1e91f4a4b3a2e95e4', from: '0xf4a4b3a2e95e4f4a3c5d2e3d5d23a1e51a5b2e8f', to: '0x4a4c5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d', detect: '安全' },
  { hash: '0x5e4f4a4b2a2e95e3f4a4c5d1e3d5d23a4e5a5b2e8f4a4c5d2e2d3d5f2a1e95e', from: '0x4f4a4b3a2e95e4f4a4c5d2e3d5d23a1e51a5b2e8', to: '0xf4a4c5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d', detect: '安全' },
  { hash: '0x4f4a4b3a1e95e4f3a4c5d2e2d3d5d23a4e5a5b2e5f4a4c5d2e3d5f2a2e95e4f', from: '0x4a4b3a2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4', to: '0xa4c5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2', detect: '安全' },
  { hash: '0xe4f4a4b31e95e4f2a4c5d2e3d3d5d23a4e5a5b2e8f4a4c5d2e3d5f2a1e95e4f', from: '0x4a4b3a2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4', to: '0xa4c5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2', detect: '危险' },
  { hash: '0x4a4b3a2e85e4f4a3c5d2e3d4d23a1e54a5b2e8f3a4c5d2e4d5f2a1e15e4f4a4', from: '0xb3a2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c', to: '0x5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d', detect: '安全' },
  { hash: '0xb3a2e95e3f4a4c52d2e3d5d13a1e5a4b4e8f4a4c3d2e3d5f1a2e95e2f4a4b3a', from: '0x2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2', to: '0xe3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2', detect: '安全' },
  { hash: '0xa1e95e4f3a4c5d24e3d5d23a2e5a5b2e5f4a4c5d1e3d5f2a3e95e4f3a4b3a2e', from: '0x95e4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3', to: '0xd5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1', detect: '安全' },
  { hash: '0x95e4f4a43c5d2e3d4d23a1e54a5b2e8f3a4c5d2e3d5f2a1e94e4f4a4b3a2e95', from: '0xe4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3d5', to: '0xf2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1e9', detect: '安全' },
  { hash: '0xe4f4a4c52d2e3d5d13a1e5a4b3e8f4a4c2d2e3d5f1a2e95e3f4a4b3a1e95e4f', from: '0x4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3d5f2a', to: '0x1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1e95e4', detect: '安全' },
  { hash: '0x4a4c5d2e2d3d5d232a1e5a4b1e8f4a4c3d2e3d5f4a2e95e4f3a4b3a2e15e4f4', from: '0xa4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3d5f2a1', to: '0xe95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1e95e4f', detect: '安全' },
  { hash: '0x4c5d2e3d4d23a1e53a5b2e8f2a4c5d2e1d5f2a1e95e4f4a4b2a2e95e3f4a4b3', from: '0xa2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d', to: '0x2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f', detect: '安全' },
  { hash: '0x4b3a2e9514f4a4c5e2e3d5d232a1e5a4b3e8f4a4c2d2e3d5f1a2e95e4f3a4b3a', from: '0x1e5a4b3e8f4a4c5d2e3d5d23a1e51a5b2e8f4a4c', to: '0x5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d', detect: '安全' },
  { hash: '0x2e95e4f423c5d2e3e5d23a1e54a5b2e8f1a4c5d2e3d5f2a1e94e4f4a4b1a2e95', from: '0xe4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3d5', to: '0xf2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1e9', detect: '安全' },
   ];
   const alternateData = [ 
   { hash: '0x16c5fdc1bb6fa919e3195bb3c7c19a6ea86bcc934ca531c6e8b6820ad8111125', from: '0xecf040xecf043eb3639adadeea90969b04c61685c217af3', to: '0x28c6c06298d514db089934071355e5743bf21d60', detect: '安全' },
{ hash: '0x580200a75fea59e60068bd3ae0b1d7631db527908945f26da3ee76db48cd63a8', from: '0xc9f5296eb3ac266c94568d790b6e91eba7d76a11', to: '0x2818e54e0489274f61f33f163504074bee5932ca', detect: '安全' },
{ hash: '0x96e776a8e6bb12e9e806069996e37f9ce0d530f4eff19c43431aad6599649272', from: '0x267be1c1d684f78cb4f6a176c4911b741e4ffdc0', to: '0xeae7380dd4cef6fbd1144f49e4d1e6964258a4f4', detect: '安全' },
{ hash: '0xd3054318320e5e00b8ed64253d4ef26bae8520274576501129dd7da2e7b50b7c', from: '0xfd9238dcd679316c6a95c08490e049fcaa9c979e', to: '0xcffad3200574698b78f32232aa9d63eabd290703', detect: '安全' },
{ hash: '0xd3b4b87a0364cada1834b6e0317a431973857384c00a52813d05fd5df90be66c', from: '0x8a05546645ac44e7e05aaf846e2be9d4528ac851', to: '0xb01cb49fe0d6d6e47edf3a072d15dfe73155331c', detect: '安全' }, 
   { hash: '0x8945f128be684ce3c7e783eb322fb849ec824ac6449c37df94bf17d542236753', from: '0x2f59b4a0086ac8a5f36cf39377db1ff2624a00b4', to: '0xecf043eb3639adadeea90969b04c61685c217af3', detect: '安全' },
   { hash: '0xa5554fdbac0d8fb69c56aaba53ec9f05f8387f7709533b40ff8ae1120d765ad2', from: '0x28c6c06298d514db089934071355e5743bf21d60', to: '0xf17aced3c7a8daa29ebb90db8d1b6efd8c364a18', detect: '安全' },
  { hash: '0xa1ca13518b3e37d7c41257ec37716f81ddeaa9f4daec884df1bb31a6bc4e6c7e', from: '0x41e3910651bcafb53feee98a164c19ced2bbd27e', to: '0x477b8d5ef7c2c42db84deb555419cd817c336b6f', detect: '安全' },
  { hash: '0x463fe4e29369403bf91f190b0ad73da29055ba13ddb7d24a2bee68127807c944', from: '0x1c68c3de2b02d9ae478d37c7e6c92a53ff01fc66', to: '0xa5995359b9941e060e366b4ee3ebb6a9f47649be', detect: '危险' },
  { hash: '0xb7554f96afc57daccfbcf27edbfc207ffcd9f52a9cedcf57fc1d152c3ed2f958', from: '0xbf94f0ac752c739f623c463b5210a7fb2cbb420b', to: '0x452a7bcd14fe5a37cdecd0925df824fd01562b86', detect: '安全' },
  { hash: '0x1cd4f3cb39a5bf5529ed3f912b4514ed49cf0bad1cc6e50589a33aa55924b0ca', from: '0x85464b207d7c1fce8da13d2f3d950c796e399a9c', to: '0x1c68c3de2b02d9ae478d37c7e6c92a53ff01fc66', detect: '安全' },
  { hash: '0xa08e5f1794d2b5d5655fd3f5de9a442b349cd8e12bf31467a377eb8ddd49a01e', from: '0x32d4703e5834f1b474b17dfdb0ac32cc22575145', to: '0xcffad3200574698b78f32232aa9d63eabd290703', detect: '安全' },
  { hash: '0x26dc67f904557e6f9d8e15d7765a2a0ae306521d6dc6b853ea4fb2a42fa1c909', from: '0x21a31ee1afc51d94c2efccaa2092ad1028285549', to: '0x32d4703e5834f1b474b17dfdb0ac32cc22575145', detect: '安全' },
  { hash: '0x1b52307bc103035cbc675e122492098cfd82213503a5fabb801928c0ad03ff3f', from: '0xfa6f469580b1caa4934817f6f8e6c0e1a94ff4e1', to: '0xfa6f469580b1caa4934817f6f8e6c0e1a94ff4e1', detect: '安全' },
  { hash: '0x771d5d5f3d5e3f5a5b2d8a2e95b4f4a4c5e1d3d5d23a1e5a5b2e8f4a4c5d1e3d', from: '0xa3f5d5f3a5e3d5a5b2a2e95e1f4a4b3a5e3d5f3a', to: '0xb2d8a2e95f4a4c5e1d3d5d23a1e5a5b2e8f4a4c5', detect: '安全' },
  { hash: '0xb1e5a5f2d8a2e93f4a4c5e1c3d5d21a1e5a2b2e8d4a4c3e1d3d2a2e95f4a4b3a', from: '0x5e3f5a5b3a2e95e4f4a4b3a2e1d3d5f3a5e3f5a5', to: '0xd23a1e5a4b2e8f2a4c5d1e3d5d23a2e95f4a4b3a', detect: '危险' },
  { hash: '0x5d23a1e4a5b2e85f4a4c5e2d3d5d13a1e5a4b2e8a4c5e2d3d5f2a1e95f4a4b3', from: '0xe95f4a4b5a2e95e2f4a4c5d2e3d5d21a1e5a4b2e', to: '0xf4a4c5e13d5d23a4e5a5b2e8a4c5d2e3d5f2a1e9', detect: '安全' },
  { hash: '0x3d5d23a2e5a5b14e8f4a4c2d1e3d5e3a1e5a4b2e5f4a4c5d2e3d2a1e95f4a4b3', from: '0x5f4a4b3a3e95f4a2c5d2e3d4d23a1e5a1b2e8f4a', to: '0x4c5d2e3d3d23a1e5a5b2e8f2a4c5d1e4d5f2a1e9', detect: '安全' },
  { hash: '0x2a1e5a4e2e8f4a3c5d2e3d4d23a1e5a5b2e8f4a1c5d2e3d5f2a3e95f4a4b3a2', from: '0xe95f4a4b4a2e95e3f4a4c5d1e3d5d23a2e5a5b2e', to: '0x8f4a4c5d3e3d5d22a1e5a4b3e8f4a4c2d2e3d5f2', detect: '安全' },
  { hash: '0x1e5a4b2e3f4a4c54d2e3d5d12a1e5a5b3e8f4a4c2d2e3d5f1a2e95e4f4a4b3a', from: '0xa1e95f4a3b3a2e954f4a4c5d2e4d5d23a1e2a5b2', to: '0xe8f4a4c5d2e3d5f21a1e5a4b2e8f4a4c3d2e3d5f', detect: '安全' },
  { hash: '0x4b2e8f4a2c5d2e34d5d23a1e5a5b2e8f3a4c5d2e4d5f2a1e91f4a4b3a2e95e4', from: '0xf4a4b3a2e95e4f4a3c5d2e3d5d23a1e51a5b2e8f', to: '0x4a4c5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d', detect: '安全' },
  { hash: '0x5e4f4a4b2a2e95e3f4a4c5d1e3d5d23a4e5a5b2e8f4a4c5d2e2d3d5f2a1e95e', from: '0x4f4a4b3a2e95e4f4a4c5d2e3d5d23a1e51a5b2e8', to: '0xf4a4c5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d', detect: '安全' },
  { hash: '0x4f4a4b3a1e95e4f3a4c5d2e2d3d5d23a4e5a5b2e5f4a4c5d2e3d5f2a2e95e4f', from: '0x4a4b3a2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4', to: '0xa4c5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2', detect: '安全' },
  { hash: '0xe4f4a4b31e95e4f2a4c5d2e3d3d5d23a4e5a5b2e8f4a4c5d2e3d5f2a1e95e4f', from: '0x4a4b3a2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4', to: '0xa4c5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2', detect: '危险' },
  { hash: '0x4a4b3a2e85e4f4a3c5d2e3d4d23a1e54a5b2e8f3a4c5d2e4d5f2a1e15e4f4a4', from: '0xb3a2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c', to: '0x5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d', detect: '安全' },
  { hash: '0xb3a2e95e3f4a4c52d2e3d5d13a1e5a4b4e8f4a4c3d2e3d5f1a2e95e2f4a4b3a', from: '0x2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2', to: '0xe3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2', detect: '安全' },
  { hash: '0xa1e95e4f3a4c5d24e3d5d23a2e5a5b2e5f4a4c5d1e3d5f2a3e95e4f3a4b3a2e', from: '0x95e4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3', to: '0xd5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1', detect: '安全' },
  { hash: '0x95e4f4a43c5d2e3d4d23a1e54a5b2e8f3a4c5d2e3d5f2a1e94e4f4a4b3a2e95', from: '0xe4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3d5', to: '0xf2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1e9', detect: '安全' },
  { hash: '0xe4f4a4c52d2e3d5d13a1e5a4b3e8f4a4c2d2e3d5f1a2e95e3f4a4b3a1e95e4f', from: '0x4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3d5f2a', to: '0x1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1e95e4', detect: '安全' },
  { hash: '0x4a4c5d2e2d3d5d232a1e5a4b1e8f4a4c3d2e3d5f4a2e95e4f3a4b3a2e15e4f4', from: '0xa4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3d5f2a1', to: '0xe95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1e95e4f', detect: '安全' },
  { hash: '0x4c5d2e3d4d23a1e53a5b2e8f2a4c5d2e1d5f2a1e95e4f4a4b2a2e95e3f4a4b3', from: '0xa2e95e4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d', to: '0x2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f', detect: '安全' },
  { hash: '0x4b3a2e9514f4a4c5e2e3d5d232a1e5a4b3e8f4a4c2d2e3d5f1a2e95e4f3a4b3a', from: '0x1e5a4b3e8f4a4c5d2e3d5d23a1e51a5b2e8f4a4c', to: '0x5d2e3d5f2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d', detect: '安全' },
  { hash: '0x2e95e4f423c5d2e3e5d23a1e54a5b2e8f1a4c5d2e3d5f2a1e94e4f4a4b1a2e95', from: '0xe4f4a4c5d2e3d5d23a1e51a5b2e8f4a4c5d2e3d5', to: '0xf2a1e95e4f4a4b3a2e95e2f4a4c5d2e3d5f2a1e9', detect: '安全' },
   ];
   
   const data = ref(initialData);
   const isLoading = ref(false);
   const isInitialData = ref(true);
   
   const displayedData = computed(() => {
    return data.value;
   });
   
   const updateData = () => {
    isLoading.value = true;
    setTimeout(() => {
   data.value = isInitialData.value ? alternateData : initialData;
   isInitialData.value = !isInitialData.value;
   isLoading.value = false;
    }, 1000);  
   };
   
   const truncateHash = (hash) => {
    return hash ? `${hash.slice(0, 6)}...${hash.slice(-4)}` : '';
   };
   </script>
   
   <style scoped>
   .container {
    background-color: rgba(0, 24, 72, 0.8);
    border-radius: 1rem;
    box-shadow: 0px 6px 12px rgba(0, 0, 0, 0.2);
    padding: 1rem;
    margin: 1.5rem;  
    color: white;
   }
   
   .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
   }
   
   .title {  
    font-size: 1.5rem;
    font-weight: bold;
   }
   
   .update-button {
    background-color: #3498db;
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 0.5rem;
    cursor: pointer;
    transition: background-color 0.3s;
   }
   
   .update-button:hover {
    background-color: #2980b9;
   }
   
   .update-button:disabled {  
    opacity: 0.5;
    cursor: not-allowed;
   }
   
   .loading-icon {
    display: inline-block; 
    animation: spin 1s linear infinite;
    margin-right: 0.5rem;
   }
   
   .table-container {  
 max-height: 400px; /* 设置表格的最大高度 */
 overflow-y: scroll; /* 始终显示垂直滚动条 */
}
   
   table {
    width: 100%;
    border-collapse: collapse;
   }  
   
   th, td {
    padding: 0.75rem;
    text-align: left;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);  
   }
   
   th {
    background-color: rgba(255, 255, 255, 0.1); 
    font-weight: bold;
   }
   
   .even-row {
    background-color: rgba(255, 255, 255, 0.05);
   }  
   
   .danger {
    color: #e74c3c;  
   }
   
   .safe {
    color: #2ecc71;
   }
   
   .truncate {  
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 120px;
   }
   
   @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }  
   }
   </style>