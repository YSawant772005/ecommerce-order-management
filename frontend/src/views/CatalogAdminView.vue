<template>
  <div class="page-head">
    <h2>Catalog <span class="muted">· MongoDB only</span></h2>
    <span class="page-hint">🗄️ {{ items.length }} products in collection</span>
  </div>

  <div v-if="state === 'loading'" class="state-pill">LOADING</div>
  <div v-else-if="state === 'error'" class="state-pill error">ERROR: {{ error }}</div>
  <div v-else>
    <div class="card table-card">
      <div class="table-head">
        <strong>Products</strong>
        <button class="btn sm" @click="newProduct">+ New product</button>
      </div>
      <table>
        <tr><th>SKU</th><th>Title</th><th>Price</th><th>Category</th><th>Active</th><th></th></tr>
        <tr v-for="p in items" :key="p._id" :class="{ editing: form._id === p._id }">
          <td class="sku">{{ p.sku }}</td>
          <td class="p-name">{{ p.title }}</td>
          <td class="money">{{ formatMoney(p.price) }}</td>
          <td><span class="cat-chip">{{ p.category }}</span></td>
          <td><span class="badge" :class="p.active ? 'shipped' : 'pending'">{{ p.active ? 'ACTIVE' : 'DRAFT' }}</span></td>
          <td class="right"><button class="btn ghost sm" @click="edit(p)">Edit</button></td>
        </tr>
      </table>
    </div>
  </div>

  <!-- Floating product form (new + edit) -->
  <Teleport to="body">
    <div v-if="formOpen" class="modal-backdrop" @click.self="cancelEdit">
      <div class="modal-card" role="dialog" aria-modal="true">
        <div class="form-title">
          <div>
            <strong>{{ form._id ? 'Edit product' : 'New product' }}</strong>
            <div class="muted" v-if="form._id">SKU {{ form.sku || '—' }} · details below are optional</div>
            <div class="muted" v-else>Title, price and category are enough to start.</div>
          </div>
          <button class="btn ghost sm" @click="cancelEdit">✕ Close</button>
        </div>

        <div class="row">
          <label class="field grow-2"><span>Title *</span>
            <input v-model="form.title" placeholder="e.g. Desk Lamp LED" />
          </label>
          <label class="field"><span>Price *</span>
            <input v-model="form.price" placeholder="0.00" inputmode="decimal" />
          </label>
          <div class="field"><span>Category *</span><UiDropdown v-model="form.category" :options="catOptions" /></div>
        </div>

        <div class="row">
          <label class="field"><span>SKU</span>
            <input v-model="form.sku" placeholder="e.g. SKU-001" />
          </label>
          <div class="field grow-2">
            <span>Tags</span>
            <div class="chips" @click="focusTag">
              <span class="chip" v-for="(t, i) in tags" :key="t">
                {{ t }}<b class="chip-x" @click.stop="tags.splice(i, 1)">×</b>
              </span>
              <input
                ref="tagInput" v-model="tagDraft" class="chip-input"
                placeholder="Type a tag, press Enter"
                @keydown.enter.prevent="addTag" @blur="addTag"
              />
            </div>
          </div>
        </div>

        <!-- Attribute / variant rows. Required on create (backend rule), optional on edit. -->
        <div class="advanced">
          <button type="button" class="adv-toggle" @click="showAdvanced = !showAdvanced">
            <span class="adv-arrow">{{ showAdvanced ? '▾' : '▸' }}</span>
            More details
            <span class="req-tag" v-if="!form._id">required</span>
            <span class="muted">attributes &amp; variants</span>
          </button>

          <div v-if="showAdvanced" class="adv-body">
            <div class="adv-block">
              <div class="adv-head">
                <strong>Attributes</strong>
                <span class="muted">key → value facts</span>
                <button type="button" class="btn ghost sm" @click="attrs.push({ key: '', value: '' })">+ Add</button>
              </div>
              <div class="adv-row" v-for="(a, i) in attrs" :key="i">
                <input v-model="a.key" placeholder="Key (e.g. color)" />
                <input v-model="a.value" placeholder="Value (e.g. red)" />
                <button type="button" class="rm" title="Remove" @click="attrs.splice(i, 1)">×</button>
              </div>
              <div v-if="!attrs.length" class="adv-empty muted">No attributes</div>
            </div>

            <div class="adv-block">
              <div class="adv-head">
                <strong>Variants</strong>
                <span class="muted">one row per option</span>
                <button type="button" class="btn ghost sm" @click="variants.push({ sku: '', color: '', stock: '', price: '' })">+ Add</button>
              </div>
              <div class="adv-legend" v-if="variants.length">
                <span>SKU</span><span>Color</span><span>Stock</span><span>Price</span><span></span>
              </div>
              <div class="adv-row variant" v-for="(v, i) in variants" :key="i">
                <input v-model="v.sku" placeholder="SKU" />
                <input v-model="v.color" placeholder="Color" />
                <input v-model="v.stock" placeholder="Stock" inputmode="numeric" />
                <input v-model="v.price" placeholder="Price" inputmode="decimal" />
                <button type="button" class="rm" title="Remove" @click="variants.splice(i, 1)">×</button>
              </div>
              <div v-if="!variants.length" class="adv-empty muted">No variants</div>
            </div>
          </div>
        </div>

        <div class="row form-actions">
          <label class="switch">
            <input type="checkbox" v-model="form.active" />
            <span class="switch-track"><span class="switch-knob"></span></span>
            Active
          </label>
          <button class="btn" :disabled="!canSave" @click="save">Save</button>
          <span class="req-hint muted" v-if="!canSave">{{ saveHint }}</span>
          <span v-if="msg" class="state-pill" :class="msg.startsWith('SUCCESS') ? 'success' : 'error'">{{ msg }}</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createProduct, listProducts, updateProduct } from '../api/products.js'
import { formatMoney } from '../utils/money.js'
import UiDropdown from '../components/UiDropdown.vue'

const catOptions = [
  { value: 'peripherals', label: 'Peripherals' },
  { value: 'audio', label: 'Audio' },
  { value: 'cables', label: 'Cables' },
  { value: 'office', label: 'Office' }
]

const items = ref([])
const state = ref('idle')
const error = ref('')
const msg = ref('')
const formOpen = ref(false)
const blank = { sku: '', title: '', price: '', category: '', active: true }
const form = ref({ ...blank })

/* Friendlier editors replace the raw JSON text fields. */
const tags = ref([])
const tagDraft = ref('')
const tagInput = ref(null)
const attrs = ref([])          // [{ key, value }]
const variants = ref([])       // [{ sku, color, stock, price }]
const showAdvanced = ref(false)

const canSave = computed(() => {
  const basics =
    String(form.value.title).trim() !== '' &&
    String(form.value.price).trim() !== '' &&
    form.value.category !== ''
  if (!basics) return false
  /* Create-only rule (backend app/models/product.py): a document must carry
     at least one attribute and one variant. ProductUpdate has no such check. */
  if (form.value._id) return true
  return attrs.value.some((a) => String(a.key).trim() !== '') &&
    variants.value.some((v) => String(v.sku).trim() !== '')
})
const saveHint = computed(() => {
  if (String(form.value.title).trim() === '' || String(form.value.price).trim() === '' || form.value.category === '')
    return 'Title, price and category are required'
  if (!form.value._id) return 'New products need 1 attribute + 1 variant'
  return ''
})

async function load() {
  state.value = 'loading'
  try {
    items.value = await listProducts({ include_inactive: true, limit: 100 })
    state.value = 'success'
  } catch (e) {
    state.value = 'error'
    error.value = e.message
  }
}
function focusTag() { tagInput.value?.focus() }
function addTag() {
  const parts = tagDraft.value.split(',').map((t) => t.trim()).filter(Boolean)
  for (const p of parts) if (!tags.value.includes(p)) tags.value.push(p)
  tagDraft.value = ''
}
function resetForm(advancedOpen = false) {
  form.value = { ...blank }
  tags.value = []
  tagDraft.value = ''
  attrs.value = []
  variants.value = []
  showAdvanced.value = advancedOpen
  msg.value = ''
}
function edit(p) {
  form.value = {
    _id: p._id, sku: p.sku, title: p.title, price: p.price, category: p.category, active: p.active
  }
  tags.value = [...(p.tags || [])]
  attrs.value = Object.entries(p.attributes || {}).map(([key, value]) => ({ key, value: String(value) }))
  variants.value = (p.variants || []).map((v) => ({
    sku: v.sku || '', color: v.color || '', stock: v.stock ?? '', price: v.price ?? ''
  }))
  /* Open the details only when there is something to see. */
  showAdvanced.value = attrs.value.length > 0 || variants.value.length > 0
  msg.value = ''
  formOpen.value = true
}
function newProduct() {
  resetForm(false)
  attrs.value = [{ key: '', value: '' }]
  variants.value = [{ sku: '', color: '', stock: '', price: '' }]
  formOpen.value = true
}
function cancelEdit() {
  resetForm(false)
  formOpen.value = false
}
async function save() {
  if (!canSave.value) return
  msg.value = ''
  try {
    const payload = {
      sku: form.value.sku,
      title: form.value.title,
      price: form.value.price,
      category: form.value.category,
      tags: [...tags.value],
      attributes: Object.fromEntries(
        attrs.value.filter((a) => String(a.key).trim() !== '')
          .map((a) => [a.key.trim(), a.value])
      ),
      variants: variants.value
        .filter((v) => String(v.sku).trim() !== '')
        .map((v) => ({
          sku: v.sku.trim(),
          color: String(v.color).trim() === '' ? null : v.color.trim(),
          stock: v.stock === '' ? 0 : Number(v.stock) || 0,
          price: v.price === '' || v.price === null ? null : Number(v.price)
        })),
      active: form.value.active
    }
    if (form.value._id) await updateProduct(form.value._id, payload)
    else await createProduct(payload)
    resetForm(false)
    formOpen.value = false
    await load()
  } catch (e) {
    msg.value = 'ERROR: ' + e.message
  }
}

/* Lock background scroll + Escape-to-close while the modal is open. */
watch(formOpen, (open) => { document.body.style.overflow = open ? 'hidden' : '' })
function onKey(e) { if (e.key === 'Escape' && formOpen.value) cancelEdit() }
onMounted(() => { load(); window.addEventListener('keydown', onKey) })
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})
</script>
<style>
.page-head { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.page-hint {
  font-size: 12px; color: var(--ink-soft); background: var(--card);
  border: 1px solid var(--line); border-radius: 999px; padding: 6px 14px;
}
.sku { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; color: var(--ink-soft); }
.p-name { font-weight: 650; }
.money { font-weight: 650; }
.right { text-align: right; }
.cat-chip {
  display: inline-block; padding: 3px 12px; border-radius: 999px;
  background: var(--accent-soft); color: var(--accent); font-size: 12px; font-weight: 650;
  text-transform: capitalize;
}
tr.editing { background: var(--accent-soft); }
tr.editing:hover { background: var(--accent-soft); }

/* ---------- floating modal ---------- */
.modal-backdrop {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(15, 23, 42, .45); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  padding: 24px; overflow-y: auto;
  animation: modal-fade 180ms ease;
}
.modal-card {
  background: var(--card); border: 1px solid var(--line); border-radius: 22px;
  width: min(760px, 100%); padding: 24px;
  box-shadow: 0 30px 70px rgba(15, 23, 42, .35);
  animation: modal-pop 320ms cubic-bezier(0.34, 1.56, 0.64, 1);
  max-height: calc(100vh - 48px); overflow-y: auto;
}
@keyframes modal-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes modal-pop {
  from { opacity: 0; transform: translateY(24px) scale(.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.form-title {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 14px;
  padding-bottom: 14px; margin-bottom: 6px; border-bottom: 1px dashed var(--line);
}
.form-title strong { font-size: 18px; }

.field { gap: 5px; }
.field span { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #94a3b8; }
.field input, .adv-row input {
  padding: 10px 14px; border-radius: 12px; border: 1px solid var(--line);
  font: inherit; color: var(--ink); background: #fff;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}
.field input:focus, .adv-row input:focus {
  outline: 0; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79,70,229,.15);
}
.grow { flex: 1; min-width: 130px; }
.grow-2 { flex: 2; min-width: 180px; }

/* Tag chips */
.chips {
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  padding: 7px 10px; border: 1px solid var(--line); border-radius: 12px; background: #fff;
  min-height: 42px; cursor: text; transition: border-color 160ms ease, box-shadow 160ms ease;
}
.chips:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79,70,229,.15); }
.chip {
  display: inline-flex; align-items: center; gap: 5px;
  background: var(--accent-soft); color: var(--accent);
  border-radius: 999px; padding: 3px 6px 3px 11px; font-size: 13px; font-weight: 650;
  animation: chip-in 200ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes chip-in { from { opacity: 0; transform: scale(.7); } to { opacity: 1; transform: scale(1); } }
.chip-x {
  width: 17px; height: 17px; border-radius: 50%; cursor: pointer;
  background: rgba(79,70,229,.18); color: var(--accent);
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; line-height: 1;
}
.chip-x:hover { background: var(--accent); color: #fff; }
.chip-input { border: 0; outline: 0; flex: 1; min-width: 120px; font: inherit; padding: 2px; background: transparent; }

/* Optional details */
.advanced { margin-top: 6px; border-top: 1px dashed var(--line); }
.adv-toggle {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 13px 2px; background: none; border: 0; font: inherit;
  font-weight: 650; color: var(--ink-soft); cursor: pointer; text-align: left;
  transition: color 160ms ease;
}
.adv-toggle:hover { color: var(--accent); }
.adv-arrow { color: var(--accent); font-size: 13px; }
.req-tag {
  background: #fef3c7; color: #92400e; border-radius: 999px;
  font-size: 10px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase;
  padding: 3px 9px;
}
.adv-body { display: flex; flex-direction: column; gap: 16px; padding-bottom: 8px; }
.adv-block { background: #f8fafc; border: 1px solid var(--line); border-radius: 16px; padding: 14px; }
.adv-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.adv-head strong { font-size: 14px; }
.adv-head .btn { margin-left: auto; }
.adv-legend, .adv-row.variant {
  display: grid; grid-template-columns: 1.4fr 1fr .7fr .7fr 28px; gap: 8px; align-items: center;
}
.adv-legend span {
  font-size: 10px; font-weight: 700; letter-spacing: .07em;
  text-transform: uppercase; color: #94a3b8; padding: 0 4px;
}
.adv-row { display: grid; grid-template-columns: 1fr 1fr 28px; gap: 8px; margin-bottom: 8px; align-items: center; }
.adv-row.variant { margin-bottom: 8px; }
.adv-row input { min-width: 0; }
.adv-row input::placeholder { color: #cbd5e1; }
.rm {
  width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--line);
  background: #fff; color: #94a3b8; font-size: 15px; line-height: 1; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: all 160ms ease;
}
.rm:hover { background: #fee2e2; border-color: #fecaca; color: #b91c1c; transform: scale(1.08); }
.adv-empty { font-size: 13px; padding: 4px; }

.form-actions { align-items: center; margin-top: 8px; border-top: 1px dashed var(--line); padding-top: 16px; }
.form-actions .state-pill { margin-bottom: 0; padding: 6px 16px; font-size: 13px; }
.req-hint { font-size: 12.5px; }

.switch { display: inline-flex; align-items: center; gap: 9px; cursor: pointer; font-size: 14px; color: var(--ink-soft); user-select: none; }
.switch input { display: none; }
.switch-track {
  width: 42px; height: 24px; border-radius: 999px; background: #cbd5e1;
  position: relative; transition: background 200ms ease; flex-shrink: 0;
}
.switch-knob {
  position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%;
  background: #fff; box-shadow: 0 2px 5px rgba(15,23,42,.25);
  transition: transform 220ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
.switch input:checked + .switch-track { background: var(--accent); }
.switch input:checked + .switch-track .switch-knob { transform: translateX(18px); }
</style>
