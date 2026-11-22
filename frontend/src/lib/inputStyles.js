/**
 * Shared input styling (Clarivo Precision Design System).
 */

const BASE =
  "mt-1 w-full rounded-[12px] border bg-white dark:bg-[#111315] px-3.5 py-2.5 text-[13.5px] text-[#0F172A] dark:text-[#F5F7FA] outline-none transition-colors disabled:cursor-not-allowed disabled:bg-[#F5F7FA] dark:disabled:bg-[#171A1D] disabled:text-[#64748B] dark:disabled:text-[#A1A1AA]";
const OK = "border-[#E4E8EE] dark:border-[#252A30] focus:ring-2 focus:ring-[#007BA7] focus:border-[#007BA7]";
const ERROR = "border-[#EF4444] focus:ring-2 focus:ring-[#EF4444] focus:border-[#EF4444]";

export function inputClass(hasError = false) {
  return `${BASE} ${hasError ? ERROR : OK}`;
}
