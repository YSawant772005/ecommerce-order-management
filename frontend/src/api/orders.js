export async function placeOrder(payload) {
  const r = await fetch('/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!r.ok) throw new Error((await r.json()).detail || 'order failed')
  return r.json()
}
export async function getOrder(id) {
  const r = await fetch(`/api/orders/${id}`)
  if (!r.ok) throw new Error('order not found')
  return r.json()
}
export async function updateStatus(id, payload) {
  const r = await fetch(`/api/orders/${id}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!r.ok) throw new Error((await r.json()).detail || 'status update failed')
  return r.json()
}
