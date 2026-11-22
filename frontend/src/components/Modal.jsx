import { X } from "lucide-react";
import { Button } from "./ui/Button";

export default function Modal({ open, title, description, children, onClose, footer }) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-black/45 p-4 backdrop-blur-sm">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-[22px] border border-[#E4E8EE] dark:border-[#252A30] bg-white dark:bg-[#111315] text-[#0F172A] dark:text-[#F5F7FA] shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-[#E4E8EE] dark:border-[#252A30] p-6">
          <div>
            <h2 className="text-[20px] font-semibold text-[#0F172A] dark:text-[#F5F7FA]">{title}</h2>
            {description ? (
              <p className="mt-1 text-[13px] text-[#64748B] dark:text-[#A1A1AA]">{description}</p>
            ) : null}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close modal">
            <X className="h-5 w-5" />
          </Button>
        </div>
        <div className="max-h-[62vh] overflow-y-auto p-6">{children}</div>
        {footer ? (
          <div className="border-t border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] p-4">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}
