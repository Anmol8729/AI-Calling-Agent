/**
 * CSV generation and download.
 *
 * `toCsv` is pure so the escaping can be tested without a DOM; `downloadCsv` is the
 * only part that touches the browser.
 */

/**
 * RFC 4180 field escaping.
 *
 * A field is quoted when it contains a comma, a quote, a line break, or leading or
 * trailing whitespace that a reader would otherwise strip. Quotes inside are doubled.
 * Without this, one note containing a comma silently shifts every later column on that
 * row into the wrong field.
 */
function escapeField(value) {
  if (value === null || value === undefined) return "";
  const s = String(value);
  const needsQuotes = /[",\r\n]/.test(s) || s !== s.trim();
  return needsQuotes ? `"${s.replace(/"/g, '""')}"` : s;
}

/**
 * Build a CSV document.
 *
 * @param columns [{ header, value }] — `value` receives a row and returns the cell.
 * @param rows    the records to write.
 *
 * CRLF line endings per RFC 4180, which is also what Excel expects.
 */
export function toCsv(columns, rows) {
  const head = columns.map((c) => escapeField(c.header)).join(",");
  const body = rows.map((row) => columns.map((c) => escapeField(c.value(row))).join(","));
  return [head, ...body].join("\r\n");
}

/** `clarivo-patients-2026-08-30` — local date, so it matches the user's own day. */
export function dateStamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/**
 * Save a CSV string as a file.
 *
 * The leading U+FEFF byte-order mark is what makes Excel read the file as UTF-8. Without
 * it Excel assumes the local ANSI codepage and Hindi names arrive as mojibake — the
 * whole point of exporting real records is that they stay readable.
 */
export function downloadCsv(filename, csv) {
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // Appended so the click works in Firefox, which ignores clicks on detached nodes.
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
