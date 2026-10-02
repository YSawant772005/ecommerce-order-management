import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from './stores/session.js'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('./views/LoginView.vue') },
    { path: '/', component: () => import('./views/StorefrontView.vue'), meta: { role: 'user' } },
    { path: '/checkout', component: () => import('./views/CheckoutView.vue'), meta: { role: 'user' } },
    { path: '/admin', redirect: '/admin/orders', meta: { role: 'admin' } },
    { path: '/admin/orders', component: () => import('./views/AdminSearchView.vue'), meta: { role: 'admin' } },
    { path: '/admin/orders/:id', component: () => import('./views/OrderDetailView.vue'), meta: { role: 'admin' } },
    { path: '/admin/catalog', component: () => import('./views/CatalogAdminView.vue'), meta: { role: 'admin' } }
  ]
})

router.beforeEach((to) => {
  const session = useSession()
  if (to.path === '/login' && session.isAuthenticated) return session.isAdmin ? '/admin' : '/'
  if (to.meta.role && !session.isAuthenticated) return { path: '/login', query: { redirect: to.fullPath } }
  if (to.meta.role === 'admin' && !session.isAdmin) return '/'
})

export default router
