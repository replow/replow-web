<script setup lang="ts">
const year = new Date().getFullYear();
</script>

<template>
  <footer class="layout-footer">
    © {{ year }}&nbsp;
    <a
      class="hover:text-primary!"
      href="https://www.preview.replow.org/"
      target="_blank"
      rel="noopener noreferrer"
      >Silune</a
    >
    <span class="footer-separator" aria-hidden="true">·</span>
    <span>SilverCode</span>
  </footer>
</template>

<style lang="scss" scoped>
.layout-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 0 0 8px;
  font-size: 12px;
}

.footer-separator {
  margin: 0 8px;
}
</style>
