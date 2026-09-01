const styles = {
  success: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  warning: "bg-amber-50 text-amber-700 ring-amber-200",
  danger: "bg-red-50 text-red-700 ring-red-200",
  // For states that are neither good nor bad, only noteworthy — a contact the agent has
  // not met yet, for instance. Reads as informational rather than as a warning.
  info: "bg-blue-50 text-blue-700 ring-blue-200",
  neutral: "bg-gray-100 text-gray-700 ring-gray-200",
  dark: "bg-brand-500 text-white ring-brand-500",
};

export function Badge({ children, tone = "neutral" }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${styles[tone]}`}>
      {children}
    </span>
  );
}
