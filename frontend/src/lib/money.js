/**
 * Money and usage formatting shared by the Billing page and the Current Plan card.
 *
 * These lived in Billing.jsx. They moved here when the Current Plan card became its
 * own component: both still need them, and a component file that also exports plain
 * functions breaks React Fast Refresh (react-refresh/only-export-components).
 */

export const nf = new Intl.NumberFormat("en-IN");

export function formatPrice(priceInr) {
  if (priceInr === null || priceInr === undefined) return "Pricing on request";
  if (priceInr === 0) return "Free";
  return `₹${nf.format(priceInr)}/mo`;
}

/** Progress-bar colour by percent of allowance consumed. */
export function barTone(percent) {
  if (percent >= 100) return "bg-red-500";
  if (percent >= 75) return "bg-amber-500";
  return "bg-emerald-500";
}
