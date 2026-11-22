import { Inbox } from "lucide-react";

export default function EmptyState({
  title = "Nothing here yet",
  description = "New records will appear here automatically.",
  icon: Icon = Inbox,
  action = null,
}) {
  return (
    <div className="grid min-h-60 place-items-center rounded-[22px] border-2 border-dashed border-[#CBD5E1] dark:border-[#252A30] bg-white dark:bg-[#111315] p-8 text-center shadow-[0_1px_3px_rgba(15,23,42,0.02)]">
      <div>
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[#007BA7]/10 text-[#007BA7] border border-[#007BA7]/20">
          <Icon className="h-5 w-5" />
        </div>
        <p className="mt-4 text-[16px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-sm text-[13px] leading-5 text-[#64748B] dark:text-[#A1A1AA]">
            {description}
          </p>
        )}
        {action && <div className="mt-5 flex justify-center">{action}</div>}
      </div>
    </div>
  );
}
