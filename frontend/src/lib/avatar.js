/**
 * Initial-letter avatars for table rows.
 *
 * Shared by the Calls and Patients tables so a person looks the same in both.
 */

const TONES = [
  "bg-blue-50 text-blue-700",
  "bg-emerald-50 text-emerald-700",
  "bg-violet-50 text-violet-700",
  "bg-amber-50 text-amber-700",
  "bg-rose-50 text-rose-700",
];

/** First character of a name, or of the phone number when there is no name. */
export function initialOf(s) {
  return (s || "?").trim().charAt(0).toUpperCase();
}

/**
 * Tint derived from the string, so one person keeps the same colour across rows,
 * pages and refreshes instead of shuffling on every render.
 */
export function avatarTone(s) {
  let h = 0;
  for (let i = 0; i < (s || "").length; i += 1) h = (h * 31 + s.charCodeAt(i)) % 997;
  return TONES[h % TONES.length];
}
