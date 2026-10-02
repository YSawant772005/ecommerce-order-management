<template>
  <div class="card product">
    <div class="p-art" :class="art.tone">
      <span class="p-emoji">{{ art.emoji }}</span>
      <span class="p-chip">{{ product.category }}</span>
    </div>
    <div class="p-title">{{ product.title }}</div>
    <div class="p-desc">{{ product.description }}</div>
    <div class="p-meta">{{ highlight || 'In stock · Ships in 24h' }}</div>
    <div class="p-buy">
      <div class="price">{{ formatMoney(product.price) }}</div>
      <button class="btn dark-btn" @click="$emit('add', product, $event)">🛒 Add</button>
    </div>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { formatMoney } from '../utils/money.js'
const props = defineProps({ product: Object })
defineEmits(['add'])
const highlight = computed(() =>
  Object.entries(props.product.attributes || {}).slice(0, 2)
    .map(([k, v]) => `${k}: ${v}`).join(' · ')
)
/* Products have no photos — pastel gradient block + category emoji stands in,
   matching the mockup's color-card aesthetic. */
const ART = {
  audio: { emoji: '🎧', tone: 'art-pink' },
  office: { emoji: '💡', tone: 'art-yellow' },
  cables: { emoji: '🔌', tone: 'art-purple' },
  peripherals: { emoji: '⌨️', tone: 'art-blue' }
}
const art = computed(() => ART[props.product.category] || { emoji: '🛍️', tone: 'art-mint' })
</script>
<style>
.product { display: flex; flex-direction: column; gap: 6px; padding: 14px; }
.p-art {
  height: 150px; border-radius: 16px; display: flex; align-items: center; justify-content: center;
  position: relative; margin-bottom: 6px;
}
.p-emoji {
  font-size: 62px; filter: drop-shadow(0 10px 16px rgba(15,23,42,.18));
  transition: transform 260ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
.product:hover .p-emoji { transform: translateY(-8px) rotate(-6deg) scale(1.1); }
.art-pink { background: linear-gradient(150deg, #fce7f3, #fbcfe8); }
.art-yellow { background: linear-gradient(150deg, #fef9c3, #fde68a); }
.art-purple { background: linear-gradient(150deg, #ede9fe, #ddd6fe); }
.art-blue { background: linear-gradient(150deg, #dbeafe, #bfdbfe); }
.art-mint { background: linear-gradient(150deg, #d1fae5, #a7f3d0); }
.p-chip {
  position: absolute; top: 10px; left: 10px; background: rgba(255,255,255,.8);
  border-radius: 999px; font-size: 11px; font-weight: 700; padding: 4px 10px; color: var(--ink);
}
.p-title { font-weight: 700; font-size: 16px; }
.p-desc {
  color: var(--ink-soft); font-size: 13px; line-height: 1.45; min-height: 38px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.p-meta { color: #94a3b8; font-size: 12px; margin-bottom: 8px; }
.p-buy { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; }
.p-buy .price { font-size: 21px; margin: 0; }
</style>
