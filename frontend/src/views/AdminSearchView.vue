<template>
  <div class="page-head">
    <h2>Orders <span class="muted">· Elasticsearch only</span></h2>
    <span class="page-hint">🔍 Live search across indexed orders</span>
  </div>

  <div class="card filter-card">
    <div class="search-bar">
      <span class="search-ico">🔍</span>
      <input v-model="search.q" placeholder="Name, title, email…" @keyup.enter="search.run(true)" />
      <button class="btn" @click="search.run(true)">Search</button>
    </div>
    <div class="filter-row">
      <div class="msdrop">
        <button class="msdrop-btn" @click="showStatus = !showStatus">
          {{ statusLabel }} <span class="chev">▾</span>
        </button>
        <div v-if="showStatus" class="msdrop-panel">
          <label v-for="o in statusOptions" :key="o.value" class="msdrop-opt">
            <input type="checkbox" :value="o.value" v-model="search.statuses" @change="search.run(true)" />
            {{ o.label }}
          </label>
          <button class="msdrop-close" @click="showStatus = false">Done</button>
        </div>
      </div>
      <label class="date-pill"><span>From</span><input type="date" v-model="search.date_from" @change="search.run(true)" /></label>
      <label class="date-pill"><span>To</span><input type="date" v-model="search.date_to" @change="search.run(true)" /></label>
      <input class="num-pill" v-model="search.price_min" placeholder="min $" @keyup.enter="search.run(true)" />
      <input class="num-pill" v-model="search.price_max" placeholder="max $" @keyup.enter="search.run(true)" />
      <button class="btn ghost sm" @click="reset">Reset</button>
    </div>
  </div>

  <div v-if="search.state === 'loading'" class="state-pill">LOADING</div>
  <div v-else-if="search.state === 'error'" class="state-pill error">ERROR: {{ search.error }}</div>
  <div v-else-if="search.state === 'empty'" class="state-pill">EMPTY — no orders match</div>

  <div v-else-if="search.result">
    <div class="cards">
      <div class="card kpi">
        <div class="kpi-label">💰 Revenue (filtered)</div>
        <div class="price">{{ formatMoney(search.result.revenue) }}</div>
        <div class="kpi-sub">across {{ search.result.total }} orders</div>
      </div>
      <div class="card kpi">
        <div class="kpi-label">📦 Orders</div>
        <div class="price">{{ search.result.total }}</div>
        <div class="kpi-sub">page {{ search.page }} of {{ pages }}</div>
      </div>
      <div class="card kpi">
        <div class="kpi-label">🧾 By status</div>
        <div class="facet-chips">
          <span v-for="(n, s) in search.result.status_facets" :key="s" class="badge" :class="String(s).toLowerCase()">{{ s }} · {{ n }}</span>
        </div>
      </div>
    </div>

    <div class="card table-card">
      <div class="table-head">
        <strong>Results</strong>
        <span class="muted">sorted by date · page {{ search.page }}</span>
      </div>
      <table>
        <tr><th>Order</th><th>Date</th><th>Customer</th><th>Total</th><th>Status</th><th></th></tr>
        <tr v-for="h in search.result.hits" :key="h.order_id">
          <td class="order-id">#{{ h.order_id }}</td>
          <td>{{ h.order_date.slice(0, 10) }}</td>
          <td>
            <span class="avatar">{{ initials(h.customer.name) }}</span>
            {{ h.customer.name }}
          </td>
          <td class="money">{{ formatMoney(h.total_amount) }}</td>
          <td><span class="badge" :class="h.status.toLowerCase()">{{ h.status }}</span></td>
          <td class="right"><RouterLink class="btn ghost sm" :to="`/admin/orders/${h.order_id}`">Detail</RouterLink></td>
        </tr>
      </table>
      <div class="pager">
        <button class="btn ghost sm" :disabled="search.page <= 1" @click="search.page--; search.run()">← Prev</button>
        <span class="pager-page">Page {{ search.page }} / {{ pages }}</span>
        <button class="btn ghost sm" :disabled="search.page >= pages" @click="search.page++; search.run()">Next →</button>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useSearch } from '../stores/search.js'
import { formatMoney } from '../utils/money.js'

const search = useSearch()
const showStatus = ref(false)
const statusOptions = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'PROCESSING', label: 'Processing' },
  { value: 'SHIPPED', label: 'Shipped' }
]
const statusLabel = computed(() =>
  search.statuses.length ? `Status (${search.statuses.length})` : 'All statuses'
)
const pages = computed(() =>
  Math.max(1, Math.ceil((search.result?.total || 0) / search.size))
)
function initials(name = '') {
  const parts = String(name).trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]?.toUpperCase() || '').join('') || '?'
}
function reset() {
  search.q = ''
  search.statuses = []
  search.date_from = ''
  search.date_to = ''
  search.price_min = ''
  search.price_max = ''
  search.run(true)
}
onMounted(() => search.run(true))
</script>
<style>
.page-head { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.page-hint {
  font-size: 12px; color: var(--ink-soft); background: var(--card);
  border: 1px solid var(--line); border-radius: 999px; padding: 6px 14px;
}
.filter-card { padding: 18px; margin-bottom: 16px; }
.search-bar { display: flex; align-items: center; gap: 10px; }
.search-ico { font-size: 15px; opacity: .7; }
.search-bar input {
  flex: 1; min-width: 0; padding: 12px 18px; border-radius: 999px;
  border: 1px solid var(--line); font: inherit; background: #f8fafc;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}
.search-bar input:focus {
  outline: 0; border-color: var(--accent); background: #fff;
  box-shadow: 0 0 0 4px rgba(79,70,229,.14);
}
.filter-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 12px; }
.date-pill {
  display: inline-flex; align-items: center; gap: 7px; padding: 7px 14px;
  border: 1px solid var(--line); border-radius: 999px; background: #fff;
  font-size: 13px; color: var(--ink-soft); transition: border-color 160ms ease;
}
.date-pill:hover { border-color: #c7d2fe; }
.date-pill span { font-weight: 650; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #94a3b8; }
.date-pill input { border: 0; background: transparent; font: inherit; color: var(--ink); padding: 0; }
.date-pill input:focus { outline: 0; }
.num-pill {
  width: 96px; padding: 9px 16px; border-radius: 999px; border: 1px solid var(--line);
  font: inherit; background: #fff; transition: border-color 160ms ease, box-shadow 160ms ease;
}
.num-pill:focus { outline: 0; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79,70,229,.14); }

.kpi-label { font-size: 13px; color: var(--ink-soft); font-weight: 650; }
.kpi-sub { font-size: 12px; color: #94a3b8; margin-top: 4px; }
.facet-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }

.order-id { font-weight: 700; color: var(--accent); }
.money { font-weight: 650; }
.right { text-align: right; }
.avatar {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 50%; margin-right: 8px;
  background: linear-gradient(140deg, #c7d2fe, #e9d5ff); color: #3730a3;
  font-size: 11px; font-weight: 800; vertical-align: middle;
}
.pager {
  display: flex; align-items: center; justify-content: center; gap: 14px;
  padding: 14px; border-top: 1px solid var(--line); background: #f8fafc;
}
.pager-page { font-size: 13px; color: var(--ink-soft); font-weight: 650; }

.msdrop { position: relative; }
.msdrop-btn {
  padding: 9px 16px; border-radius: 999px; border: 1px solid #e2e8f0;
  background: #fff; color: #0f172a; font: inherit; font-weight: 550; cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}
.msdrop-btn:hover { border-color: #c7d2fe; box-shadow: 0 0 0 3px rgba(79,70,229,.12); }
.msdrop-btn .chev { color: #4f46e5; }
.msdrop-panel {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: 30; min-width: 180px;
  background: #fff; border: 1px solid #e2e8f0; border-radius: 14px;
  box-shadow: 0 12px 30px rgba(15,23,42,.16); padding: 8px;
  display: flex; flex-direction: column; gap: 2px;
  animation: fx-rise 200ms cubic-bezier(0.22, 0.61, 0.36, 1);
}
.msdrop-opt { display: flex; gap: 8px; align-items: center; padding: 8px 10px; border-radius: 9px; cursor: pointer; }
.msdrop-opt:hover { background: #f1f5f9; }
.msdrop-close { margin-top: 4px; padding: 8px; border-radius: 999px; border: 0; background: #eef2ff; color: #4f46e5; font-weight: 600; cursor: pointer; }
</style>
