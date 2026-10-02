import { defineStore } from 'pinia'

export const useCart = defineStore('cart', {
  state: () => ({ lines: [] }),
  actions: {
    add(productId, qty = 1, title = '', category = '') {
      const line = this.lines.find((l) => l.product_id === productId)
      if (line) line.quantity += qty
      else this.lines.push({ product_id: productId, quantity: qty, title, category })
    },
    clear() {
      this.lines = []
    }
  }
})
