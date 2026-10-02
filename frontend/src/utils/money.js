// Money arrives as a JSON string ("50.16"). Format without float math.
export function formatMoney(str) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(str)
}
