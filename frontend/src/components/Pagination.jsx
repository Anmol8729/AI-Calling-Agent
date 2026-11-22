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
    "grid h-8 min-w-8 place-items-center rounded-full px-2 text-xs font-medium transition disabled:opacity-30 disabled:pointer-events-none";

  return (
    <nav className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pt-2" aria-label={label}>
      <p className="text-xs text-[#64748B] dark:text-[#A1A1AA]">
        Showing <span className="font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{first}</span> to <span className="font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{last}</span> of <span className="font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{total}</span> {unit}
      </p>

      {pages > 1 && (
        <div className="flex items-center gap-1">
          <button
            type="button"
            className={`${btn} text-[#64748B] hover:bg-[#F5F7FA] hover:text-[#0F172A] dark:text-[#A1A1AA] dark:hover:bg-[#171A1D] dark:hover:text-[#F5F7FA]`}
            onClick={() => go(page - 1)}
            disabled={page === 1}
            aria-label="Previous page"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>

          {pageNumbers(page, pages).map((n, i) =>
            n === "gap" ? (
              <span key={`gap-${i}`} className="px-1 text-xs text-[#64748B] dark:text-[#A1A1AA]" aria-hidden="true">…</span>
            ) : (
              <button
                key={n}
                type="button"
                className={`${btn} ${
                  n === page
                    // Selected state: Clarivo Cerulean
                    ? "bg-[#007BA7] font-semibold text-white shadow-sm"
                    : "text-[#64748B] hover:bg-[#F5F7FA] hover:text-[#0F172A] dark:text-[#A1A1AA] dark:hover:bg-[#171A1D] dark:hover:text-[#F5F7FA]"
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
            className={`${btn} text-[#64748B] hover:bg-[#F5F7FA] hover:text-[#0F172A] dark:text-[#A1A1AA] dark:hover:bg-[#171A1D] dark:hover:text-[#F5F7FA]`}
            onClick={() => go(page + 1)}
            disabled={page === pages}
            aria-label="Next page"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {showSizePicker && (
        <select
          className="rounded-full border border-[#E4E8EE] dark:border-[#252A30] bg-[#FFFFFF] dark:bg-[#171A1D] px-3 py-1.5 text-xs text-[#0F172A] dark:text-[#F5F7FA] focus:border-[#007BA7] focus:outline-none"
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
