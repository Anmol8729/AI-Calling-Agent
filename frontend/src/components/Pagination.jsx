import { ChevronLeft, ChevronRight } from "lucide-react";
import { pageNumbers } from "../lib/pagination";

/**
 * Page controls for a client-side paginated table.
 *
 * Renders nothing when everything fits on one page: a lone "1" with both arrows
 * disabled is furniture, not information.
 */
export default function Pagination({ page, pageSize, total, onChange, unit = "items" }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0 || pages === 1) return null;

  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  const go = (n) => onChange(Math.min(Math.max(n, 1), pages));

  const btn = "grid h-8 min-w-8 place-items-center rounded-xl px-2 text-sm transition disabled:opacity-40 disabled:pointer-events-none";

  return (
    <nav className="flex flex-col-reverse items-center justify-between gap-3 sm:flex-row" aria-label="Call history pages">
      <p className="text-xs text-gray-500">
        Showing {first} to {last} of {total} {unit}
      </p>
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
                  ? "bg-gray-950 font-semibold text-white"
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
    </nav>
  );
}
