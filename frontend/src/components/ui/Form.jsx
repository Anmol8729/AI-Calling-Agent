import { inputClass } from "../../lib/inputStyles";

export function Section({ icon: Icon, iconTone, title, subtitle, action, children }) {
  return (
    <section className="clarivo-panel p-5 space-y-4">
      <div className="flex items-start justify-between gap-3 border-b border-[#E4E8EE] dark:border-[#252A30] pb-3">
        <div className="flex items-start gap-2.5">
          {Icon && (
            iconTone ? (
              <span className={`mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full ${iconTone}`}>
                <Icon className="h-5 w-5" />
              </span>
            ) : (
              <Icon className="mt-0.5 h-5 w-5 shrink-0 text-[#007BA7]" />
            )
          )}
          <div>
            <h2 className="text-[18px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] leading-[24px]">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[12px] text-[#64748B] dark:text-[#A1A1AA]">{subtitle}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Label({ children, htmlFor }) {
  return (
    <label
      htmlFor={htmlFor}
      className="block text-[11px] font-semibold uppercase tracking-[0.05em] text-[#64748B] dark:text-[#A1A1AA]"
    >
      {children}
    </label>
  );
}

export function Hint({ children, id }) {
  return <p id={id} className="mt-1 text-[12px] text-[#64748B] dark:text-[#A1A1AA]">{children}</p>;
}

export function FieldError({ children, id }) {
  return (
    <p id={id} role="alert" className="mt-1 text-xs font-medium text-[#EF4444]">
      {children}
    </p>
  );
}

export function Field({
  label, value, onChange, placeholder, hint, error,
  id, type = "text", disabled = false, inputMode, autoComplete, maxLength,
  onBlur, rightSlot, hintSlot,
}) {
  const hintId = id ? `${id}-hint` : undefined;
  const errorId = id ? `${id}-error` : undefined;
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <div className={rightSlot ? "relative" : undefined}>
        <input
          id={id}
          type={type}
          className={`${inputClass(!!error)}${rightSlot ? " pr-11" : ""}`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          placeholder={placeholder}
          disabled={disabled}
          inputMode={inputMode}
          autoComplete={autoComplete}
          maxLength={maxLength}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : hint ? hintId : undefined}
        />
        {rightSlot}
      </div>
      {error ? (
        <FieldError id={errorId}>{error}</FieldError>
      ) : (
        (hint || hintSlot) && (
          <div className="flex items-start justify-between gap-3">
            {hint ? <Hint id={hintId}>{hint}</Hint> : <span />}
            {hintSlot}
          </div>
        )
      )}
    </div>
  );
}
