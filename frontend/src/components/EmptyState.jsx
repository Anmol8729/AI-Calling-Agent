import { Inbox } from "lucide-react";

// A blank screen is where new users get stuck, so an empty state should say what
// this page is for and offer the next step. Pass `action` (a Button/Link) to give
// the user somewhere to go instead of leaving them at a dead end.
export default function EmptyState({
  title = "Nothing here yet",
  description = "New records will appear here automatically.",
  icon: Icon = Inbox,
  action = null,
}) {
  return (
    <div className="grid min-h-52 place-items-center rounded-3xl border border-dashed border-gray-300 bg-white p-8 text-center">
      <div>
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-gray-100 text-gray-500">
          <Icon className="h-5 w-5" />
        </div>
        <p className="mt-4 text-sm font-semibold text-gray-950">{title}</p>
        {description && <p className="mx-auto mt-1 max-w-sm text-sm leading-6 text-gray-500">{description}</p>}
        {action && <div className="mt-5 flex justify-center">{action}</div>}
      </div>
    </div>
  );
}
