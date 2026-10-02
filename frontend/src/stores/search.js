import { defineStore } from 'pinia'
import { searchOrders } from '../api/search.js'

// Screen 3 state. Talks to /api/search/orders (Elasticsearch) only —
// never to the orders or catalog stores.
export const useSearch = defineStore('search', {
  state: () => ({
    q: '',
    statuses: [],
    date_from: '',
    date_to: '',
    price_min: '',
    price_max: '',
    page: 1,
    size: 10,
    result: null,
    state: 'idle',
    error: ''
  }),
  actions: {
    async run(resetPage = false) {
      if (resetPage) this.page = 1
      this.state = 'loading'
      try {
        const payload = { q: this.q || null, page: this.page, size: this.size }
        if (this.statuses.length) payload.statuses = this.statuses
        if (this.date_from) payload.date_from = new Date(this.date_from).toISOString()
        if (this.date_to) payload.date_to = new Date(this.date_to).toISOString()
        if (this.price_min !== '') payload.price_min = this.price_min
        if (this.price_max !== '') payload.price_max = this.price_max
        this.result = await searchOrders(payload)
        this.state = this.result.total ? 'success' : 'empty'
      } catch (e) {
        this.state = 'error'
        this.error = e.message
      }
    }
  }
})
