<template>
  <div class="cdd" :class="{ open }">
    <span v-if="label" class="dd-label">{{ label }}</span>
    <button type="button" class="cdd-btn" :disabled="disabled" @click="open = !open">
      <span class="cdd-current">{{ currentLabel }}</span>
      <span class="chev">▾</span>
    </button>
    <div v-if="open" class="cdd-backdrop" @click="open = false"></div>
    <ul v-if="open" class="cdd-list">
      <li
        v-for="o in options" :key="o.value"
        class="cdd-opt" :class="{ sel: String(o.value) === String(modelValue) }"
        @click="pick(o.value)"
      >{{ o.label }}</li>
    </ul>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] },
  label: { type: String, default: '' },
  placeholder: { type: String, default: 'Select…' },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'change'])
const open = ref(false)
const currentLabel = computed(() => {
  const hit = props.options.find((o) => String(o.value) === String(props.modelValue))
  return hit ? hit.label : props.placeholder
})
function pick(v) {
  open.value = false
  emit('update:modelValue', v)
  emit('change', v)
}
</script>
<style>
.cdd { position: relative; display: inline-flex; flex-direction: column; gap: 4px; }
.dd-label { font-size: 12px; font-weight: 600; color: #475569; }
.cdd-btn {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 9px 14px; border-radius: 999px; border: 1px solid #e2e8f0;
  background: #fff; color: #0f172a; font: inherit; font-weight: 550; cursor: pointer;
  max-width: 240px;
}
.cdd-btn:hover { border-color: #c7d2fe; }
.cdd-btn .chev { color: #4f46e5; }
.cdd-current { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cdd-btn:disabled { opacity: .5; cursor: not-allowed; }
.cdd-backdrop { position: fixed; inset: 0; z-index: 9; }
.cdd-list {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: 10; margin: 0; padding: 6px;
  list-style: none; min-width: 100%; background: #fff; border: 1px solid #e2e8f0;
  border-radius: 12px; box-shadow: 0 8px 24px rgba(15,23,42,.12);
}
.cdd-opt { padding: 9px 12px; border-radius: 8px; cursor: pointer; white-space: nowrap; }
.cdd-opt:hover { background: #f1f5f9; }
.cdd-opt.sel { background: #eef2ff; color: #4f46e5; font-weight: 650; }
</style>
