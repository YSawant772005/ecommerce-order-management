<template>
  <span class="badge queued" v-if="status === 'QUEUED'">QUEUED</span>
  <span class="badge pending" v-else>{{ status }}</span>
</template>
<script setup>
defineProps({ status: String })
</script>
