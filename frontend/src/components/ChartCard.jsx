export default function ChartCard({ title, description, children, action }) {
  return (
    <section className="clarivo-panel p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-[#0F172A] dark:text-[#F5F7FA]">{title}</h2>
          {description ? <p className="mt-1 text-xs text-[#64748B] dark:text-[#A1A1AA]">{description}</p> : null}
        </div>
        {action}
      </div>
      <div className="h-72">{children}</div>
    </section>
  );
}
