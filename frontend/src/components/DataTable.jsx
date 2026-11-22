import EmptyState from "./EmptyState";
import LoadingState from "./LoadingState";

export default function DataTable({
  columns,
  rows,
  loading = false,
  emptyTitle = "No records found",
  emptyDescription,
  emptyIcon,
  emptyAction,
}) {
  if (loading) {
    return <LoadingState />;
  }

  if (!rows.length) {
    return (
      <EmptyState
        title={emptyTitle}
        {...(emptyDescription ? { description: emptyDescription } : {})}
        {...(emptyIcon ? { icon: emptyIcon } : {})}
        action={emptyAction}
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-[22px] border border-[#E4E8EE] dark:border-[#252A30] bg-white dark:bg-[#111315] shadow-[0_1px_3px_rgba(15,23,42,0.02)]">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-[#E4E8EE]/70 dark:divide-[#252A30]">
          <thead className="bg-[#F5F7FA] dark:bg-[#171A1D]">
            <tr>
              {columns.map((column, idx) => (
                <th
                  key={column.key}
                  className={`px-5 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[#475569] dark:text-[#A1A1AA] ${
                    idx === 0 ? "first:rounded-l-xl" : ""
                  } ${idx === columns.length - 1 ? "last:rounded-r-xl" : ""}`}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#E4E8EE]/70 dark:divide-[#252A30]">
            {rows.map((row, index) => (
              <tr
                key={row.id || index}
                className="hover:bg-[#F5F7FA]/50 dark:hover:bg-[#171A1D]/50 transition-colors"
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className="whitespace-nowrap px-5 py-3.5 text-[13px] text-[#0F172A] dark:text-[#F5F7FA]"
                  >
                    {column.render ? column.render(row) : row[column.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
