import EmptyState from "./EmptyState";
import LoadingState from "./LoadingState";

export default function DataTable({
  columns,
  rows,
  loading = false,
  emptyTitle = "No records found",
  // Forwarded to EmptyState so each table can explain itself and offer a next step.
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
    <div className="overflow-hidden rounded-3xl border border-gray-200 bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              {columns.map((column) => (
                <th key={column.key} className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((row, index) => (
              <tr key={row.id || index} className="hover:bg-gray-50/70">
                {columns.map((column) => (
                  <td key={column.key} className="whitespace-nowrap px-5 py-4 text-sm text-gray-700">
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
