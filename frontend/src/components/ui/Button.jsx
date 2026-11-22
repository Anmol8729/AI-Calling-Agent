export function Button({
  children,
  variant = "primary",
  size = "md",
  className = "",
  ...props
}) {
  const variants = {
    primary: "bg-[#007BA7] text-white hover:opacity-90 shadow-sm",
    accent: "bg-[#FF2D95] text-white hover:opacity-95 shadow-[0_1px_3px_rgba(255,45,149,0.25)] font-semibold",
    secondary: "bg-white dark:bg-[#111315] text-[#0F172A] dark:text-[#F5F7FA] border border-[#E4E8EE] dark:border-[#252A30] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] shadow-[0_1px_2px_rgba(15,23,42,0.02)]",
    ghost: "text-[#64748B] dark:text-[#A1A1AA] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] hover:text-[#0F172A] dark:hover:text-[#F5F7FA]",
    danger: "bg-[#EF4444] text-white hover:opacity-90 shadow-sm",
  };
  const sizes = {
    sm: "h-8 px-3 text-[12px]",
    md: "h-9 px-4 text-[13px]",
    lg: "h-11 px-5 text-[14px]",
    icon: "h-9 w-9 p-0",
  };

  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-full font-medium transition cursor-pointer disabled:pointer-events-none disabled:opacity-50 ${variants[variant] || variants.primary} ${sizes[size] || sizes.md} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
