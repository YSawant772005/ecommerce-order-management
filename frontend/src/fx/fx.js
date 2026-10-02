/** Floating UI effects: fly-to-cart, spark burst, toast.
 *
 * Plain reactive module (no Pinia) shared by the overlay component and the
 * views that trigger effects. Every effect is self-cleaning: entries are
 * removed by id after their CSS animation finishes.
 */
import { reactive } from 'vue'

export const fx = reactive({ flyers: [], toasts: [], sparks: [] })

let seq = 0
const nextId = () => ++seq
const cartPill = () => document.querySelector('.cart')

/** Cart pill bounce — call when a flyer lands (or immediately as fallback). */
export function bumpCart() {
  const el = cartPill()
  if (!el) return
  el.classList.remove('bump')
  void el.offsetWidth // restart the CSS animation
  el.classList.add('bump')
  setTimeout(() => el.classList.remove('bump'), 500)
}

/** Pill with the product title flying from `fromEl` to the cart pill. */
export function flyToCart(product, fromEl) {
  const target = cartPill()
  if (!fromEl || !target) {
    bumpCart()
    return
  }
  const a = fromEl.getBoundingClientRect()
  const b = target.getBoundingClientRect()
  const flyer = {
    id: nextId(),
    label: product.title || 'Item',
    x: a.left + a.width / 2,
    y: a.top + a.height / 2,
    dx: b.left + b.width / 2 - (a.left + a.width / 2),
    dy: b.top + b.height / 2 - (a.top + a.height / 2),
  }
  fx.flyers.push(flyer)
  setTimeout(() => {
    fx.flyers = fx.flyers.filter((f) => f.id !== flyer.id)
    bumpCart()
  }, 680)
}

/** Rising "+1"/"✦" sparks scattered around `fromEl`. */
export function burst(fromEl) {
  if (!fromEl) return
  const r = fromEl.getBoundingClientRect()
  const cx = r.left + r.width / 2
  const cy = r.top + r.height / 2
  for (let i = 0; i < 6; i++) {
    const spark = {
      id: nextId(),
      x: cx,
      y: cy,
      dx: (Math.random() - 0.5) * 130,
      dy: -(45 + Math.random() * 70),
      char: i % 2 ? '✦' : '+1',
    }
    fx.sparks.push(spark)
    setTimeout(() => {
      fx.sparks = fx.sparks.filter((s) => s.id !== spark.id)
    }, 800)
  }
}

/** Floating confirmation toast, top-right under the header. */
export function toast(title) {
  const t = { id: nextId(), title }
  fx.toasts.push(t)
  setTimeout(() => {
    fx.toasts = fx.toasts.filter((x) => x.id !== t.id)
  }, 2600)
}
