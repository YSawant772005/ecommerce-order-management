<template>
  <section class="shop-intro">
    <div><p class="hero-eyebrow">THE NEST STORE</p><h1>Useful things for<br /><em>better days.</em></h1><p class="shop-sub">Thoughtful gear for your desk, your downtime and everywhere in between.</p></div>
    <div class="shop-stat"><strong>24h</strong><span>dispatch on<br />in-stock orders</span></div>
  </section>
  <section class="category-row" aria-label="Shop by category">
    <button v-for="c in categories" :key="c.value" :class="{ selected: category === c.value }" @click="chooseCategory(c.value)"><span>{{ c.icon }}</span>{{ c.label }}</button>
  </section>
  <section id="grid" class="products-section">
    <div class="section-head"><div><p class="eyebrow">CURATED COLLECTION</p><h2>{{ activeLabel }}</h2></div><span class="result-count">{{ catalog.items.length }} products</span></div>
    <form class="product-search" @submit.prevent="reload"><span>Search</span><input v-model="query" placeholder="Search products, categories or features" /><button class="btn" type="submit">Find</button></form>
    <div v-if="catalog.state === 'loading'" class="state-pill">Loading products...</div>
    <div v-else-if="catalog.state === 'error'" class="state-pill error">{{ catalog.error }}</div>
    <div v-else-if="catalog.state === 'empty'" class="empty-state"><strong>No products found</strong><span>Try another search or category.</span></div>
    <div v-else class="grid"><ProductCard v-for="p in catalog.items" :key="p._id || p.id" :product="p" @add="add" /></div>
  </section>
  <section class="features"><div class="feature"><span class="f-ico">01</span><div><strong>Easy checkout</strong><p>Clear prices, simple ordering.</p></div></div><div class="feature"><span class="f-ico">02</span><div><strong>Fast dispatch</strong><p>Most orders leave within 24 hours.</p></div></div><div class="feature"><span class="f-ico">03</span><div><strong>Made to last</strong><p>Useful products, chosen carefully.</p></div></div></section>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useCatalog } from '../stores/catalog.js'
import { useCart } from '../stores/cart.js'
import { flyToCart, burst, toast } from '../fx/fx.js'
import ProductCard from '../components/ProductCard.vue'

const catalog = useCatalog()
const cart = useCart()
const category = ref('')
const query = ref('')
const categories = [
  { value: '', label: 'All products', icon: 'All' },
  { value: 'audio', label: 'Audio', icon: 'Sound' },
  { value: 'office', label: 'Office', icon: 'Desk' },
  { value: 'peripherals', label: 'Peripherals', icon: 'Tech' },
  { value: 'cables', label: 'Cables', icon: 'Power' }
]
const activeLabel = computed(() => categories.find((item) => item.value === category.value)?.label || 'All products')
async function reload() { await catalog.load({ category: category.value, search: query.value || undefined }) }
onMounted(reload)
function chooseCategory(value) { category.value = value; reload() }
async function add(product, event) {
  cart.add(product._id || product.id, 1, product.title, product.category)
  const btn = event?.currentTarget || event?.target
  await Promise.allSettled([flyToCart(event), burst(btn)])
  toast(`Added ${product.title}`)
}
</script>
<style>
.shop-intro { display: flex; align-items: end; justify-content: space-between; gap: 32px; padding: 34px 0 30px; border-bottom: 1px solid var(--line); }
.shop-intro h1 { margin: 0; font-size: clamp(42px, 6vw, 68px); line-height: .98; letter-spacing: -.06em; }
.shop-intro h1 em { color: var(--accent); font-style: italic; }
.shop-sub { max-width: 42ch; margin: 18px 0 0; color: var(--ink-soft); line-height: 1.6; font-size: 16px; }
.shop-stat { display: flex; align-items: center; gap: 12px; padding: 17px 20px; border-left: 2px solid var(--accent); color: var(--ink-soft); font-size: 12px; line-height: 1.4; }
.shop-stat strong { color: var(--ink); font-size: 28px; }
.eyebrow { color: var(--accent); font-size: 11px; font-weight: 800; letter-spacing: .16em; margin: 0 0 12px; }
.category-row { display: flex; gap: 8px; flex-wrap: wrap; padding: 22px 0; }
.category-row button { display: inline-flex; align-items: center; gap: 8px; padding: 9px 14px; border: 1px solid var(--line); border-radius: 999px; background: var(--card); color: var(--ink-soft); cursor: pointer; font: inherit; font-size: 13px; }
.category-row button span { color: var(--accent); font-size: 10px; font-weight: 800; text-transform: uppercase; }
.category-row button.selected, .category-row button:hover { border-color: var(--accent); background: var(--accent-soft); color: var(--ink); }
.products-section { scroll-margin-top: 90px; }
.products-section .section-head { margin: 12px 0 18px; align-items: end; }
.products-section .section-head h2 { margin: 0; }
.result-count { color: var(--ink-soft); font-size: 13px; }
.product-search { display: flex; align-items: center; gap: 10px; padding: 6px 6px 6px 16px; margin-bottom: 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
.product-search span { color: var(--accent); font-size: 11px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
.product-search input { flex: 1; min-width: 0; border: 0; padding: 10px; background: transparent; font: inherit; color: var(--ink); }
.product-search input:focus { outline: 0; }
.product-search .btn { border-radius: 8px; padding: 10px 18px; }
.empty-state { display: flex; flex-direction: column; gap: 7px; padding: 45px 20px; border: 1px dashed var(--line); text-align: center; color: var(--ink-soft); }
/* ---------- hero ---------- */
.hero {
  display: flex; align-items: center; justify-content: space-between; gap: 40px;
  background: linear-gradient(135deg, #eef2ff 0%, #fdf2f8 55%, #fefce8 100%);
  border: 1px solid var(--line); border-radius: 28px;
  padding: 56px 56px; margin-bottom: 28px;
  animation: fx-rise 500ms cubic-bezier(0.22, 0.61, 0.36, 1) backwards;
}
.hero-eyebrow {
  font-size: 12px; letter-spacing: .18em; font-weight: 700;
  color: var(--accent); margin-bottom: 14px;
}
.hero-title { font-size: 54px; line-height: 1.05; margin: 0 0 14px; font-weight: 800; letter-spacing: -0.02em; }
.hero-title em { font-style: italic; color: var(--accent); }
.hero-sub { color: var(--ink-soft); font-size: 17px; max-width: 46ch; margin: 0 0 26px; line-height: 1.6; }
.hero-cta { font-size: 16px; padding: 14px 30px; }
.hero-badge {
  background: var(--card); border: 1px solid var(--line); border-radius: 20px;
  padding: 20px 24px; text-align: center; box-shadow: 0 14px 30px rgba(15,23,42,.10);
  flex-shrink: 0;
  animation: fx-bob 4s ease-in-out infinite;
}
.hero-avatars { display: flex; justify-content: center; }
.hero-avatars span {
  width: 44px; height: 44px; border-radius: 50%; background: #f1f5f9;
  border: 3px solid #fff; display: inline-flex; align-items: center; justify-content: center;
  font-size: 20px; margin-left: -10px; box-shadow: 0 3px 8px rgba(15,23,42,.12);
}
.hero-avatars span:first-child { margin-left: 0; }
.hero-rating { font-size: 14px; color: var(--ink-soft); margin-top: 10px; }
.hero-rating strong { display: block; font-size: 22px; color: var(--ink); }
.hero-stars { color: #f59e0b; letter-spacing: 3px; font-size: 14px; margin-top: 4px; }

/* ---------- showcase cards ---------- */
.showcase { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-bottom: 34px; }
.show-card {
  border-radius: 24px; padding: 22px; min-height: 210px;
  display: flex; flex-direction: column; justify-content: space-between;
  border: 1px solid rgba(15,23,42,.06); position: relative; overflow: hidden;
  transition: transform 240ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 240ms ease;
  animation: fx-rise 460ms cubic-bezier(0.22, 0.61, 0.36, 1) backwards;
}
.show-card:nth-child(2) { animation-delay: 80ms; }
.show-card:nth-child(3) { animation-delay: 160ms; }
.show-card:hover { transform: translateY(-6px); box-shadow: 0 18px 36px rgba(15,23,42,.14); }
.show-card.pink { background: linear-gradient(150deg, #fce7f3, #fbcfe8); }
.show-card.yellow { background: linear-gradient(150deg, #fef9c3, #fde68a); }
.show-card.purple { background: linear-gradient(150deg, #ede9fe, #ddd6fe); }
.show-tag {
  align-self: flex-start; background: rgba(255,255,255,.75); border-radius: 999px;
  font-size: 12px; font-weight: 700; padding: 5px 14px; color: var(--ink);
}
.show-art { font-size: 64px; line-height: 1; text-align: right; filter: drop-shadow(0 8px 14px rgba(15,23,42,.18)); transition: transform 260ms cubic-bezier(0.34, 1.56, 0.64, 1); }
.show-card:hover .show-art { transform: translateY(-6px) rotate(-6deg) scale(1.06); }
.show-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.show-name { font-weight: 750; font-size: 17px; }
.show-hint { font-size: 13px; color: #475569; }
.show-go {
  width: 46px; height: 46px; border-radius: 50%; border: 0; cursor: pointer;
  background: var(--ink); font-size: 19px; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  transition: transform 180ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 180ms ease;
}
.show-go:hover { transform: translateY(-3px) scale(1.08); box-shadow: 0 8px 18px rgba(15,23,42,.35); }
.show-go:active { transform: scale(.94); }

/* ---------- section head ---------- */
.section-head {
  display: flex; align-items: flex-end; justify-content: space-between; gap: 20px;
  flex-wrap: wrap; margin-top: 8px; scroll-margin-top: 90px;
}
.section-head h2 { margin-bottom: 2px; }

/* ---------- features strip ---------- */
.features {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 40px;
}
.feature {
  display: flex; align-items: center; gap: 14px; background: var(--card);
  border: 1px solid var(--line); border-radius: var(--radius); padding: 18px 20px;
  transition: transform 220ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 220ms ease;
}
.feature:hover { transform: translateY(-4px); box-shadow: 0 12px 26px rgba(15,23,42,.10); }
.f-ico {
  width: 48px; height: 48px; border-radius: 14px; background: var(--accent-soft);
  display: inline-flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0;
}
.feature strong { display: block; font-size: 15px; }
.feature p { margin: 2px 0 0; font-size: 13px; color: var(--ink-soft); }

@media (max-width: 860px) {
  .shop-intro { align-items: flex-start; flex-direction: column; }
  .shop-stat { align-self: stretch; }
  .product-search span { display: none; }
  .hero { flex-direction: column; align-items: flex-start; padding: 34px 26px; }
  .hero-title { font-size: 38px; }
  .showcase, .features { grid-template-columns: 1fr; }
}
</style>
