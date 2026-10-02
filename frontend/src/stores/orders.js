import { defineStore } from 'pinia'
import { getOrder, placeOrder } from '../api/orders.js'

export const useOrders = defineStore('orders', {
  state: () => ({ detail: null, state: 'idle', error: '', lastPlaced: null }),
  actions: {
    async place(payload) {
      this.state = 'loading'
      try {
        this.lastPlaced = await placeOrder(payload)
        this.state = 'success'
        return this.lastPlaced
      } catch (e) {
        this.state = 'error'
        this.error = e.message
        throw e
      }
    },
    async load(id) {
      this.state = 'loading'
      try {
        this.detail = await getOrder(id)
        this.state = 'success'
      } catch (e) {
        this.state = 'error'
        this.error = e.message
      }
    }
  }
})
