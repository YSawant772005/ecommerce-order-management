<template>
  <main class="login-shell">
    <section class="login-aside">
      <RouterLink to="/login" class="login-brand"><span>N</span> Nest</RouterLink>
      <div class="aside-copy">
        <p class="eyebrow">THE EVERYDAY EDIT</p>
        <h1>Good things,<br /><em>well chosen.</em></h1>
        <p>A considered store for useful objects, thoughtful desks and better days.</p>
      </div>
      <div class="aside-note">Curated gear / Fast delivery / Human support</div>
    </section>
    <section class="login-panel">
      <div class="login-card">
        <div class="eyebrow">WELCOME BACK</div>
        <h2>Sign in to Nest</h2>
        <p class="login-sub">Choose your workspace to continue.</p>
        <div class="role-tabs">
          <button :class="{ selected: mode === 'shopper' }" @click="mode = 'shopper'">Shopper</button>
          <button :class="{ selected: mode === 'admin' }" @click="mode = 'admin'">Admin</button>
        </div>
        <form @submit.prevent="submit">
          <label v-if="mode === 'shopper'" class="field"><span>Customer</span>
            <select v-model="selectedUser">
              <option v-for="user in users" :key="user.id" :value="String(user.id)">{{ user.name }} / {{ user.email }}</option>
            </select>
          </label>
          <label class="field"><span>Email</span><input v-model="email" type="email" :placeholder="mode === 'admin' ? 'admin@nest.local' : 'you@example.com'" /></label>
          <label class="field"><span>Password</span><input v-model="password" type="password" placeholder="Password" /></label>
          <p v-if="error" class="form-error">{{ error }}</p>
          <button class="btn login-btn" type="submit">Continue <span>-&gt;</span></button>
        </form>
        <p class="demo-hint">{{ mode === 'admin' ? 'Demo admin: admin@nest.local / admin123' : 'Choose a customer account to browse and checkout.' }}</p>
      </div>
    </section>
  </main>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listUsers } from '../api/users.js'
import { useSession } from '../stores/session.js'

const route = useRoute()
const router = useRouter()
const session = useSession()
const mode = ref('shopper')
const email = ref('')
const password = ref('')
const error = ref('')
const users = ref([{ id: 1, name: 'Demo Shopper', email: 'shopper@nest.local' }])
const selectedUser = ref('1')

onMounted(async () => {
  try {
    const loaded = await listUsers()
    if (loaded.length) users.value = loaded
  } catch { /* The seeded demo account keeps login usable during API recovery. */ }
})
function submit() {
  error.value = ''
  if (mode.value === 'admin') {
    if (email.value !== 'admin@nest.local' || password.value !== 'admin123') {
      error.value = 'Use the demo admin credentials shown below.'
      return
    }
    session.loginAsAdmin()
    router.push('/admin')
    return
  }
  const user = users.value.find((item) => String(item.id) === selectedUser.value) || users.value[0]
  if (!user) { error.value = 'No customer account is available.'; return }
  session.loginAsUser(user)
  router.push(route.query.redirect || '/')
}
</script>
<style scoped>
.login-shell { min-height: 100vh; display: grid; grid-template-columns: 1.05fr .95fr; background: #f5f1e9; margin: -28px; }
.login-aside { padding: 42px clamp(28px, 7vw, 110px); display: flex; flex-direction: column; justify-content: space-between; background: radial-gradient(circle at 80% 25%, #e5bca8, transparent 35%), #1d2b28; color: #f8f3e8; }
.login-brand { color: inherit; text-decoration: none; font-size: 25px; font-weight: 800; letter-spacing: -.04em; }
.login-brand span { display: inline-grid; place-items: center; width: 34px; height: 34px; margin-right: 8px; border-radius: 50%; background: #e8a889; color: #1d2b28; }
.eyebrow { margin: 0 0 15px; color: #d98565; font-size: 11px; font-weight: 800; letter-spacing: .16em; }
.aside-copy { max-width: 500px; }
.aside-copy h1 { margin: 0; font-size: clamp(42px, 6vw, 76px); line-height: .98; letter-spacing: -.06em; }
.aside-copy h1 em { color: #e8a889; font-style: italic; }
.aside-copy p:not(.eyebrow) { max-width: 34ch; margin-top: 24px; color: #bdc9c1; font-size: 17px; line-height: 1.6; }
.aside-note { color: #bdc9c1; font-size: 12px; letter-spacing: .06em; }
.login-panel { display: grid; place-items: center; padding: 30px; background: #f5f1e9; }
.login-card { width: min(100%, 420px); }
.login-card h2 { margin-bottom: 8px; font-size: 34px; color: #1d2b28; }
.login-sub { margin: 0 0 26px; color: #708078; }
.role-tabs { display: grid; grid-template-columns: 1fr 1fr; padding: 4px; margin-bottom: 24px; background: #e8e2d7; border-radius: 12px; }
.role-tabs button { border: 0; padding: 10px; border-radius: 9px; background: transparent; color: #708078; cursor: pointer; font: inherit; font-weight: 700; }
.role-tabs button.selected { background: #fffdf8; color: #1d2b28; box-shadow: 0 3px 10px #1d2b2814; }
.field { display: flex; flex-direction: column; gap: 7px; margin-bottom: 16px; color: #53655e; font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.field input, .field select { width: 100%; border: 1px solid #d8d1c5; border-radius: 10px; padding: 13px 14px; background: #fffdf8; color: #1d2b28; font: inherit; font-size: 14px; letter-spacing: normal; text-transform: none; }
.field input:focus, .field select:focus { outline: 2px solid #e8a889; border-color: transparent; }
.login-btn { width: 100%; justify-content: space-between; border-radius: 10px; padding: 14px 17px; background: #d98565; color: #fffdf8; }
.login-btn span { font-size: 20px; }
.form-error { margin: -3px 0 14px; color: #b54e43; font-size: 13px; }
.demo-hint { margin-top: 18px; color: #8b928e; font-size: 12px; line-height: 1.5; }
@media (max-width: 760px) { .login-shell { grid-template-columns: 1fr; margin: -16px; } .login-aside { min-height: 330px; padding: 26px; } .aside-copy h1 { font-size: 47px; } .aside-note { display: none; } .login-panel { padding: 40px 24px; } }
</style>
