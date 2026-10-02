<template>
  <h2>Order Detail</h2>
  <div v-if="orders.state === 'loading'">LOADING</div>
  <div v-else-if="orders.state === 'error'">ERROR / NOT FOUND: {{ orders.error }}</div>
  <div v-else-if="orders.detail">
    <KpiCards :total="formatMoney(orders.detail.total_amount)" :status="orders.detail.status" />
    <p>Order {{ orders.detail.order_id }} · v{{ orders.detail.version }} <SyncBadge status="QUEUED" /></p>
    <div class="row">
      <UiDropdown
        v-model="statusSel" :options="statusOptions" label="Status"
        placeholder="Change status…" @change="changeStatus" />
      <span v-if="statusMsg">{{ statusMsg }}</span>
    </div>
    <table>
      <tr><th>Title</th><th>Qty</th><th>Price</th></tr>
      <tr v-for="i in orders.detail.items" :key="i.product_id">
        <td>{{ i.title }}</td><td>{{ i.quantity }}</td><td>{{ formatMoney(i.unit_price) }}</td>
      </tr>
    </table>
  </div>
</template>
<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useOrders } from '../stores/orders.js'
import { updateStatus } from '../api/orders.js'
import { formatMoney } from '../utils/money.js'
import KpiCards from '../components/KpiCards.vue'
import SyncBadge from '../components/SyncBadge.vue'
import UiDropdown from '../components/UiDropdown.vue'

const route = useRoute()
const orders = useOrders()
const statusMsg = ref('')
const statusSel = ref('')
const statusOptions = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'PROCESSING', label: 'Processing' },
  { value: 'SHIPPED', label: 'Shipped' }
]
function load() {
  statusMsg.value = ''
  orders.load(route.params.id)
}
async function changeStatus() {
  if (!statusSel.value || !orders.detail) return
  statusMsg.value = ''
  try {
    await updateStatus(route.params.id, { status: statusSel.value, expected_version: orders.detail.version })
    statusMsg.value = 'SUCCESS — status updated, search re-index queued'
    statusSel.value = ''
    load()
  } catch (e) {
    statusMsg.value = 'ERROR: ' + e.message
  }
}
onMounted(load)
watch(() => route.params.id, load)
</script>
