import { defineStore } from 'pinia'

export const useSession = defineStore('session', {
  state: () => ({
    userId: Number(localStorage.getItem('nest-user-id')) || null,
    userName: localStorage.getItem('nest-user-name') || '',
    role: localStorage.getItem('nest-role') || '',
    users: []
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.role),
    isAdmin: (state) => state.role === 'admin'
  },
  actions: {
    setUsers(users) {
      this.users = users
      if (!this.userId && users.length && this.role === 'user') this.loginAsUser(users[0])
    },
    loginAsAdmin() {
      this.userId = null; this.userName = 'Admin'; this.role = 'admin'; this.persist()
    },
    loginAsUser(user) {
      this.userId = Number(user.id); this.userName = user.name; this.role = 'user'; this.persist()
    },
    logout() {
      this.userId = null; this.userName = ''; this.role = ''
      localStorage.removeItem('nest-user-id'); localStorage.removeItem('nest-user-name'); localStorage.removeItem('nest-role')
    },
    persist() {
      localStorage.setItem('nest-user-id', String(this.userId || ''))
      localStorage.setItem('nest-user-name', this.userName)
      localStorage.setItem('nest-role', this.role)
    }
  }
})
