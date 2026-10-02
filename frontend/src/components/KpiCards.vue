<template>
  <div class="cards">
    <div class="card"><div>Order Total</div><div class="price">{{ total }}</div></div>
    <div class="card"><div>Status</div><div class="price">{{ status }}</div></div>
  </div>
</template>
<script setup>
defineProps({ total: String, status: String })
</script>
