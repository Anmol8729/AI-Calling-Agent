/**
 * Page numbers to show, with "gap" markers where pages are skipped.
 *
 * Always includes the first and last page plus a window around the current one, so the
 * control keeps a stable width instead of growing with the page count. Separate from
 * Pagination.jsx because a file exporting both a component and a plain function breaks
 * React Fast Refresh.
 *
 *   pageNumbers(1, 9)  -> [1, 2, "gap", 9]
 *   pageNumbers(5, 9)  -> [1, "gap", 4, 5, 6, "gap", 9]
 *   pageNumbers(3, 4)  -> [1, 2, 3, 4]
 */
export function pageNumbers(current, total, span = 1) {
  const wanted = new Set([1, total]);
  for (let n = current - span; n <= current + span; n += 1) {
    if (n >= 1 && n <= total) wanted.add(n);
  }

  const sorted = [...wanted].sort((a, b) => a - b);
  const out = [];
  sorted.forEach((n, i) => {
    // Only a skip of more than one page earns an ellipsis; a gap of exactly one would
    // take as much room as simply showing that page.
    if (i > 0 && n - sorted[i - 1] > 1) out.push("gap");
    out.push(n);
  });
  return out;
}
