/**
 * Section / Label / Hint / Field — the form primitives the settings screens share.
 *
 * These lived inside Setup.jsx as local helpers. They moved here when the WhatsApp
 * configuration grew into its own component: copying them would have meant two
 * definitions of the same input drifting apart, and the app's form styling is
 * exactly the thing that has to stay identical across screens.
 *
 * Every added prop is optional, so existing call sites keep their current
 * behaviour and appearance.
 */

import { inputClass } from "../../lib/inputStyles";

export function Section({ icon: Icon, iconTone, title, subtitle, action, children }) {
  return (
    <section className="panel rounded-3xl border border-gray-100 bg-white p-6 shadow-sm space-y-4">
      <div className="flex items-start justify-between gap-3 border-b border-gray-100 pb-3">
        <div className="flex items-start gap-2.5">
          {Icon && (
            iconTone ? (
              <span className={`mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full ${iconTone}`}>
                <Icon className="h-5 w-5" />
              </span>
            ) : (
              <Icon className="mt-0.5 h-5 w-5 shrink-0 text-gray-500" />
            )
          )}
          <div>
            <h2 className="text-lg font-semibold text-gray-950">{title}</h2>
            {subtitle && <p className="mt-0.5 text-sm text-gray-500">{subtitle}</p>}
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
      className="block text-xs font-semibold uppercase tracking-wider text-gray-500"
    >
      {children}
    </label>
  );
}

export function Hint({ children, id }) {
  return <p id={id} className="mt-1 text-xs text-gray-400">{children}</p>;
}

/** Inline validation message. role="alert" so a screen reader announces it when it
 *  appears, which a plain colour change never does. */
export function FieldError({ children, id }) {
  return (
    <p id={id} role="alert" className="mt-1 text-xs font-medium text-red-600">
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
