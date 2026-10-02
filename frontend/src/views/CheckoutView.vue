<template>
  <h2>Checkout</h2>
  <div v-if="state === 'loading'" class="state-pill">LOADING</div>
  <div v-if="state === 'error'" class="state-pill error">ERROR: {{ error }}</div>
  <div v-if="state === 'success' && placed" class="state-pill success">
    SUCCESS — order {{ placed.order_id }} ({{ placed.sync_status }})
  </div>

  <div class="card checkout-card">
    <div class="checkout-head">
      <strong>Your bag</strong>
      <span class="muted">{{ cart.lines.length }} item(s)</span>
    </div>
    <table v-if="cart.lines.length" class="cart-table">
      <tr><th>Product</th><th>Qty</th></tr>
      <tr v-for="l in cart.lines" :key="l.product_id">
        <td><span class="cart-emoji">{{ emojiFor(l) }}</span> {{ l.title || l.product_id }}</td>
        <td><span class="qty-chip">{{ l.quantity }}</span></td>
      </tr>
    </table>
    <div v-else-if="!placed" class="cart-empty">
      <span class="cart-empty-ico">🛒</span>
      <p>Your cart is empty — go pick something nice.</p>
    </div>
    <div class="checkout-foot">
      <button class="btn dark-btn checkout-btn" :disabled="!cart.lines.length || state === 'loading'" @click="checkout">
        Place order
      </button>
    </div>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { useCart } from '../stores/cart.js'
import { useSession } from '../stores/session.js'
import { useOrders } from '../stores/orders.js'

const cart = useCart()
const session = useSession()
const orders = useOrders()
const state = ref('idle')
const error = ref('')
const placed = ref(null)

const EMOJI = { audio: '🎧', office: '💡', cables: '🔌', peripherals: '⌨️' }
function emojiFor(line) { return EMOJI[line.category] || '🛍️' }

async function checkout() {
  state.value = 'loading'
  try {
    placed.value = await orders.place({
      user_id: session.userId,
      items: cart.lines.map((l) => ({ product_id: l.product_id, quantity: l.quantity }))
    })
    cart.clear()
    state.value = 'success'
  } catch (e) {
    state.value = 'error'
    error.value = e.message
  }
}
</script>
<style>
.checkout-card { padding: 22px; max-width: 720px; }
.checkout-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; }
.checkout-head strong { font-size: 17px; }
.cart-table { border: 0; box-shadow: none; }
.cart-table td, .cart-table th { padding: 14px; }
.cart-emoji { margin-right: 8px; }
.qty-chip {
  display: inline-flex; min-width: 30px; height: 30px; align-items: center; justify-content: center;
  background: var(--accent-soft); color: var(--accent); border-radius: 999px;
  font-weight: 700; font-size: 13px; padding: 0 8px;
}
.cart-empty { text-align: center; padding: 34px 0 22px; color: var(--ink-soft); }
.cart-empty-ico { font-size: 44px; display: block; margin-bottom: 8px; animation: fx-bob 3s ease-in-out infinite; }
.checkout-foot { display: flex; justify-content: flex-end; margin-top: 16px; }
.checkout-btn { padding: 13px 34px; font-size: 15px; }
.state-pill {
  display: inline-block; padding: 8px 18px; border-radius: 999px; font-weight: 650;
  background: var(--accent-soft); color: var(--accent); margin-bottom: 12px;
}
.state-pill.error { background: #fee2e2; color: #b91c1c; }
.state-pill.success { background: #dcfce7; color: var(--green); }
</style>
