/**
 * Shared input styling.
 *
 * Kept out of components/ui/Form.jsx because a file that exports both components and
 * plain functions breaks React Fast Refresh (react-refresh/only-export-components).
 * It lives here so a bespoke control — a <select>, or an input with a trailing button
 * — matches a plain <Field> exactly instead of approximating its classes.
 */

const BASE =
  "mt-1 w-full rounded-xl border px-3.5 py-2 text-sm focus:outline-none disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-500";
const OK = "border-gray-200 focus:border-gray-950";
const ERROR = "border-red-300 focus:border-red-500";

export function inputClass(hasError = false) {
  return `${BASE} ${hasError ? ERROR : OK}`;
}
