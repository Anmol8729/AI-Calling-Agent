import { ChevronLeft, ChevronRight } from "lucide-react";
import { pageNumbers } from "../lib/pagination";

/**
 * Page controls for a client-side paginated table.
 *
 * Renders nothing when everything fits on one page and there is no size selector: a
 * lone "1" with both arrows disabled is furniture, not information.
 *
 * `pageSizeOptions` / `onPageSizeChange` are optional, so callers that only need paging
 * keep exactly the control they had before the selector existed.
 */
export default function Pagination({
  page,
  pageSize,
  total,
  onChange,
  unit = "items",
  label = "Pages",
  pageSizeOptions,
  onPageSizeChange,
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const showSizePicker =
    Array.isArray(pageSizeOptions) && pageSizeOptions.length > 1 && typeof onPageSizeChange === "function";

  // The size selector still earns its place on a single page — it is how you get back to
  // more rows after narrowing to 10 — but with nothing to page through, nothing else is.
  if (total === 0 || (pages === 1 && !showSizePicker)) return null;

  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  const go = (n) => onChange(Math.min(Math.max(n, 1), pages));

  const btn =
    "grid h-8 min-w-8 place-items-center rounded-xl px-2 text-sm transition disabled:opacity-40 disabled:pointer-events-none";

  return (
    <nav className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between" aria-label={label}>
      <p className="text-xs text-gray-500">
        Showing {first} to {last} of {total} {unit}
      </p>

      {pages > 1 && (
        <div className="flex items-center gap-1">
          <button
            type="button"
            className={`${btn} text-gray-500 hover:bg-gray-100 hover:text-gray-950`}
            onClick={() => go(page - 1)}
            disabled={page === 1}
            aria-label="Previous page"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>

          {pageNumbers(page, pages).map((n, i) =>
            n === "gap" ? (
              <span key={`gap-${i}`} className="px-1 text-sm text-gray-400" aria-hidden="true">…</span>
            ) : (
              <button
                key={n}
                type="button"
                className={`${btn} ${
                  n === page
                    // Selected state, so brand blue rather than the structural navy.
                    ? "bg-brand-500 font-semibold text-white"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-950"
                }`}
                onClick={() => go(n)}
                aria-current={n === page ? "page" : undefined}
                aria-label={`Page ${n}`}
              >
                {n}
              </button>
            ),
          )}

          <button
            type="button"
            className={`${btn} text-gray-500 hover:bg-gray-100 hover:text-gray-950`}
            onClick={() => go(page + 1)}
            disabled={page === pages}
            aria-label="Next page"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {showSizePicker && (
        <select
          className="rounded-xl border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700 focus:border-gray-950 focus:outline-none"
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          aria-label={`Rows per page`}
        >
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>{n} per page</option>
          ))}
        </select>
      )}
    </nav>
  );
}
