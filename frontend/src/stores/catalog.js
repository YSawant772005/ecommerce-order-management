import { defineStore } from 'pinia'
import { listProducts } from '../api/products.js'

export const useCatalog = defineStore('catalog', {
  state: () => ({ items: [], state: 'idle', error: '' }),
  actions: {
    async load(params = {}) {
      this.state = 'loading'
      try {
        this.items = await listProducts(params)
        this.state = this.items.length ? 'success' : 'empty'
      } catch (e) {
        this.state = 'error'
        this.error = e.message
      }
    }
  }
})
