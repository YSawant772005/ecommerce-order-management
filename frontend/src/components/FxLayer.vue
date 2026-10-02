<template>
  <div class="fx-layer" aria-hidden="true">
    <div
      v-for="f in fx.flyers"
      :key="`f${f.id}`"
      class="fx-flyer"
      :style="{ '--x': `${f.x}px`, '--y': `${f.y}px`, '--dx': `${f.dx}px`, '--dy': `${f.dy}px` }"
    >
      <span class="fx-flyer-dot">🛒</span> {{ f.label }}
    </div>

    <span
      v-for="s in fx.sparks"
      :key="`s${s.id}`"
      class="fx-spark"
      :style="{ '--x': `${s.x}px`, '--y': `${s.y}px`, '--dx': `${s.dx}px`, '--dy': `${s.dy}px` }"
      >{{ s.char }}</span
    >

    <TransitionGroup name="fx-toast">
      <div v-for="t in fx.toasts" :key="`t${t.id}`" class="fx-toast">
        <span class="fx-toast-check">✓</span>
        <span>Added <strong>{{ t.title }}</strong></span>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { fx } from '../fx/fx.js'
</script>

<style>
/* Fixed overlay: never intercepts clicks, spans the viewport. */
.fx-layer {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 60;
}

/* ---------- fly-to-cart ---------- */
.fx-flyer {
  position: fixed;
  left: 0;
  top: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  padding: 7px 14px;
  border-radius: 999px;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  font-weight: 650;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.4);
  /* Start at the button, arc up, land on the cart pill, shrink in. */
  transform: translate(var(--x), var(--y)) translate(-50%, -50%);
  animation: fx-fly 680ms cubic-bezier(0.22, 0.61, 0.36, 1) forwards;
}
@keyframes fx-fly {
  0% {
    transform: translate(var(--x), var(--y)) translate(-50%, -50%) scale(1);
    opacity: 1;
  }
  55% {
    /* midpoint lifted above the straight line = arc */
    transform: translate(calc(var(--x) + var(--dx) * 0.55), calc(var(--y) + var(--dy) * 0.35 - 90px))
      translate(-50%, -50%) scale(1.12);
    opacity: 1;
  }
  100% {
    transform: translate(calc(var(--x) + var(--dx)), calc(var(--y) + var(--dy)))
      translate(-50%, -50%) scale(0.35);
    opacity: 0.65;
  }
}
.fx-flyer-dot { font-size: 14px; }

/* ---------- button burst sparks ---------- */
.fx-spark {
  position: fixed;
  left: 0;
  top: 0;
  font-size: 15px;
  font-weight: 800;
  color: var(--accent);
  text-shadow: 0 1px 6px rgba(79, 70, 229, 0.35);
  transform: translate(var(--x), var(--y)) translate(-50%, -50%);
  animation: fx-spark 750ms ease-out forwards;
}
@keyframes fx-spark {
  0% {
    transform: translate(var(--x), var(--y)) translate(-50%, -50%) scale(0.5);
    opacity: 0;
  }
  15% {
    transform: translate(calc(var(--x) + var(--dx) * 0.15), calc(var(--y) + var(--dy) * 0.2))
      translate(-50%, -50%) scale(1.1);
    opacity: 1;
  }
  100% {
    transform: translate(calc(var(--x) + var(--dx)), calc(var(--y) + var(--dy)))
      translate(-50%, -50%) scale(0.9);
    opacity: 0;
  }
}

/* ---------- floating toast ---------- */
.fx-toast {
  position: fixed;
  top: 74px;
  right: 24px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 11px 16px;
  border-radius: var(--radius);
  background: var(--card);
  border: 1px solid var(--line);
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.16);
  font-size: 14px;
  color: var(--ink);
  animation: fx-toast-float 2.6s ease-in-out forwards;
}
.fx-toast-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--green);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}
@keyframes fx-toast-float {
  0% {
    transform: translateX(40px) scale(0.95);
    opacity: 0;
  }
  8% {
    transform: translateX(0) scale(1);
    opacity: 1;
  }
  12% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
  82% { transform: translateY(0); opacity: 1; }
  100% { transform: translateY(-10px) scale(0.98); opacity: 0; }
}
/* TransitionGroup enter hook — CSS animation above drives the rest. */
.fx-toast-enter-active { transition: none; }
.fx-toast-leave-active { transition: opacity 200ms ease; }
.fx-toast-leave-to { opacity: 0; }

/* ---------- cart pill bounce (class toggled by bumpCart) ---------- */
.cart.bump { animation: fx-cart-bump 450ms cubic-bezier(0.34, 1.56, 0.64, 1); }
@keyframes fx-cart-bump {
  0% { transform: scale(1); }
  35% { transform: scale(1.22); box-shadow: 0 0 0 8px rgba(79, 70, 229, 0.25); }
  70% { transform: scale(0.96); }
  100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(79, 70, 229, 0); }
}
</style>
