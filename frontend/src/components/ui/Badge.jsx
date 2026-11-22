const styles = {
  success: "bg-[#22C55E]/10 text-[#15803D] dark:text-[#22C55E] ring-[#22C55E]/20",
  warning: "bg-[#F59E0B]/10 text-[#B45309] dark:text-[#F59E0B] ring-[#F59E0B]/20",
  danger: "bg-[#FF2D95]/10 text-[#FF2D95] ring-[#FF2D95]/20",
  info: "bg-[#007BA7]/10 text-[#007BA7] ring-[#007BA7]/20",
  neutral: "bg-[#F5F7FA] dark:bg-[#171A1D] text-[#64748B] dark:text-[#A1A1AA] ring-[#E4E8EE] dark:ring-[#252A30]",
  dark: "bg-[#007BA7] text-white ring-[#007BA7]",
  accent: "bg-[#FF2D95] text-white ring-[#FF2D95]",
};

export function Badge({ children, tone = "neutral" }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11.5px] font-medium ring-1 transition-colors ${
        styles[tone] || styles.neutral
      }`}
    >
      {children}
    </span>
  );
}
