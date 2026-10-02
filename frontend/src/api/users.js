export async function listUsers() {
  const r = await fetch('/api/users')
  if (!r.ok) throw new Error('users failed')
  return r.json()
}
