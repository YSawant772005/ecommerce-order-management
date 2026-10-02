export async function searchOrders(payload) {
  const r = await fetch('/api/search/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!r.ok) throw new Error('search failed')
  return r.json()
}
