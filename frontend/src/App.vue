<template>
  <div class="app" :class="{ 'admin-app': session.isAdmin }">
    <RouterView v-if="$route.path === '/login'" />
    <template v-else>
    <header class="nav">
      <RouterLink :to="session.isAdmin ? '/admin' : '/'" class="brand"><span class="logo">N</span> <span class="brand-name">Nest</span></RouterLink>
      <nav class="links">
        <template v-if="session.isAdmin">
          <RouterLink to="/admin/orders" active-class="active">Order search</RouterLink>
          <RouterLink to="/admin/catalog" active-class="active">Catalog</RouterLink>
        </template>
        <template v-else>
          <RouterLink to="/" active-class="active">Shop</RouterLink>
          <RouterLink to="/checkout" active-class="active">Checkout</RouterLink>
        </template>
      </nav>
      <div class="nav-right">
        <span class="identity"><span class="identity-dot"></span>{{ session.userName }}</span>
        <RouterLink v-if="!session.isAdmin" to="/checkout" class="cart">
          Cart <span v-if="cart.lines.length" class="cart-badge">{{ cart.lines.length }}</span>
        </RouterLink>
        <button class="logout" @click="logout">Sign out</button>
      </div>
    </header>
    <main class="body"><RouterView /></main>
    <FxLayer />
    </template>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useCart } from './stores/cart.js'
import { useSession } from './stores/session.js'
import { listUsers } from './api/users.js'
import FxLayer from './components/FxLayer.vue'

const cart = useCart()
const session = useSession()
onMounted(async () => {
  if (session.isAdmin) return
  try {
    session.setUsers(await listUsers())
  } catch {}
})
function logout() {
  session.logout()
  window.location.href = '/login'
}
</script>

<style>
:root {
  --accent: #d16f52;
  --accent-soft: #fbe8df;
  --bg: #f7f5f0;
  --card: #ffffff;
  --ink: #20312d;
  --ink-soft: #5c6d67;
  --line: #dedbd3;
  --green: #15803d;
  --radius: 16px;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font-family: Georgia, "Times New Roman", serif; }
h2 { font-weight: 700; letter-spacing: -0.01em; margin: 4px 0 16px; font-size: 28px; }

/* ---------- top navbar (mockup layout) ---------- */
.app { min-height: 100vh; display: flex; flex-direction: column; }
.nav {
  display: flex; align-items: center; gap: 26px;
  padding: 14px 28px; background: rgba(255,255,255,.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line);
  position: sticky; top: 0; z-index: 20;
}
.brand { display: inline-flex; align-items: center; gap: 8px; text-decoration: none; color: var(--ink); font-weight: 800; font-size: 21px; }
.logo { color: #fff; background: var(--accent); width: 30px; height: 30px; border-radius: 50%; display: inline-grid; place-items: center; font-size: 15px; animation: fx-bob 3.2s ease-in-out infinite; }
@keyframes fx-bob {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  50% { transform: translateY(-3px) rotate(12deg); }
}
.links { display: flex; gap: 4px; flex: 1; }
.links a {
  padding: 8px 14px; border-radius: 999px; text-decoration: none;
  color: var(--ink-soft); font-weight: 550;
  transition: background 160ms ease, color 160ms ease, transform 160ms ease;
}
.links a:hover { background: var(--accent-soft); color: var(--accent); transform: translateY(-1px); }
.links a.active { background: var(--accent-soft); color: var(--accent); font-weight: 700; }
.nav-right { display: flex; align-items: center; gap: 12px; }
.identity { display: inline-flex; align-items: center; gap: 8px; color: var(--ink-soft); font-size: 13px; font-weight: 700; }
.identity-dot { width: 8px; height: 8px; border-radius: 50%; background: #4ca276; }
.logout { border: 0; background: transparent; color: var(--ink-soft); cursor: pointer; font: inherit; font-size: 13px; }
.logout:hover { color: var(--accent); }
.search {
  width: 230px; padding: 9px 16px; border-radius: 999px;
  border: 1px solid var(--line); background: #f1f5f9; font: inherit;
}
.user, .cart {
  padding: 9px 16px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--card); text-decoration: none; color: var(--ink); font-weight: 600;
  display: inline-flex; align-items: center; gap: 7px;
  transition: transform 180ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 180ms ease;
}
.user:hover, .cart:hover { transform: translateY(-2px); box-shadow: 0 6px 14px rgba(15,23,42,.15); }
.cart { background: var(--ink); color: #fff; border-color: var(--ink); }
.cart-badge {
  background: #ef4444; color: #fff; min-width: 20px; height: 20px;
  border-radius: 999px; font-size: 12px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center; padding: 0 5px;
}

.body { padding: 28px; max-width: 1200px; width: 100%; margin: 0 auto; flex: 1; }

/* ---------- shared building blocks ---------- */
.muted { color: #94a3b8; font-size: 13px; font-weight: 400; }
.row { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; align-items: center; }
.row input { padding: 9px 14px; border-radius: 999px; border: 1px solid var(--line); font: inherit; background: #fff; transition: border-color 160ms ease, box-shadow 160ms ease; }
.row input:focus { outline: 0; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79,70,229,.15); }
h3 { margin: 22px 0 10px; font-size: 18px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 16px; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 18px; box-shadow: 0 1px 2px rgba(15,23,42,.05);
  transition: transform 220ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 220ms ease, border-color 220ms ease;
}
.card:hover { transform: translateY(-5px); box-shadow: 0 14px 30px rgba(15,23,42,.12); border-color: #c7d2fe; }
.price { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; margin-top: 4px; }
.badge { display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; background: #f1f5f9; color: #334155; }
.badge.pending { background: #fef9c3; color: #854d0e; }
.badge.queued { background: var(--accent-soft); color: var(--accent); }
.badge.processing { background: #dbeafe; color: #1d4ed8; }
.badge.shipped { background: #dcfce7; color: #15803d; }

.btn {
  background: var(--accent); color: #fff; border: 0; border-radius: 999px;
  padding: 10px 20px; font-weight: 600; cursor: pointer; font: inherit;
  transition: transform 160ms cubic-bezier(0.34, 1.56, 0.64, 1), filter 160ms ease, box-shadow 160ms ease;
}
.btn:hover { filter: brightness(.95); transform: translateY(-2px); box-shadow: 0 6px 16px rgba(79,70,229,.35); }
.btn:active { transform: translateY(0) scale(.96); box-shadow: none; }
.btn:disabled { opacity: .45; cursor: not-allowed; transform: none; box-shadow: none; }
/* Outlined pill variant (secondary actions: Edit, Prev/Next, Detail). */
.btn.ghost { background: var(--card); border: 1px solid var(--line); color: var(--ink); display: inline-flex; align-items: center; }
.btn.ghost:hover { filter: none; border-color: #c7d2fe; color: var(--accent); transform: translateY(-1px); box-shadow: 0 4px 12px rgba(15,23,42,.10); text-decoration: none; }
.btn.sm { padding: 7px 16px; font-size: 13px; }
/* Dark pill CTA from the mockup (hero, add-to-cart, place order). */
.dark-btn { background: var(--ink); border-color: var(--ink); }
.dark-btn:hover { filter: none; box-shadow: 0 6px 16px rgba(15,23,42,.35); }

/* Card-embedded table (admin pages): flush table inside a rounded card. */
.table-card { padding: 0; overflow: hidden; }
.table-card table { border: 0; border-radius: 0; box-shadow: none; }
.table-head {
  display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
  padding: 16px 18px; border-bottom: 1px solid var(--line);
}
.table-head strong { font-size: 16px; }

/* Labeled form field. */
.field { display: flex; flex-direction: column; gap: 6px; font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #94a3b8; }
.field input { padding: 10px 14px; border-radius: 12px; border: 1px solid var(--line); font: inherit; text-transform: none; letter-spacing: normal; color: var(--ink); background: #fff; transition: border-color 160ms ease, box-shadow 160ms ease; }
.field input:focus { outline: 0; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79,70,229,.15); }

/* Status/result pills. */
.state-pill {
  display: inline-block; padding: 8px 18px; border-radius: 999px; font-weight: 650;
  background: var(--accent-soft); color: var(--accent); margin-bottom: 12px;
}
.state-pill.error { background: #fee2e2; color: #b91c1c; }
.state-pill.success { background: #dcfce7; color: var(--green); }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 16px; margin-top: 16px; }
/* Cards rise into place with a soft stagger — the "floating UI" entrance. */
.grid .card { animation: fx-rise 420ms cubic-bezier(0.22, 0.61, 0.36, 1) backwards; }
.grid .card:nth-child(2) { animation-delay: 50ms; }
.grid .card:nth-child(3) { animation-delay: 100ms; }
.grid .card:nth-child(4) { animation-delay: 150ms; }
.grid .card:nth-child(5) { animation-delay: 200ms; }
.grid .card:nth-child(6) { animation-delay: 250ms; }
.grid .card:nth-child(n+7) { animation-delay: 300ms; }
@keyframes fx-rise {
  from { opacity: 0; transform: translateY(18px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

table {
  width: 100%; border-collapse: collapse; background: var(--card);
  border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden;
  box-shadow: 0 1px 2px rgba(15,23,42,.05);
}
th { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--ink-soft); background: #f8fafc; }
td, th { padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; }
tbody tr { transition: background 140ms ease; }
tbody tr:hover { background: #f8fafc; }
tr:last-child td { border-bottom: 0; }
table a { color: var(--accent); font-weight: 650; text-decoration: none; }
table a:hover { text-decoration: underline; }
input, select { font: inherit; color: var(--ink); }

@media (max-width: 960px) {
  .nav { flex-wrap: wrap; gap: 10px 16px; padding: 12px 16px; }
  .links { order: 3; flex: 0 0 100%; overflow-x: auto; padding-bottom: 2px; }
  .search { display: none; }
  .body { padding: 16px; }
}
</style>
