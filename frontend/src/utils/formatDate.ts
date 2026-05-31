/**
 * formatDate / formatDateTime — Spanish month abbreviation formatters.
 * UI-SPEC §Implementation Notes #4.
 * Month abbreviations: ene feb mar abr may jun jul ago sep oct nov dic.
 */

const MONTHS = [
  "ene", "feb", "mar", "abr", "may", "jun",
  "jul", "ago", "sep", "oct", "nov", "dic",
];

/**
 * formatDate("2026-05-31") → "31 may 2026"
 * Parses ISO date string without timezone shift by splitting on "-".
 */
export function formatDate(iso: string): string {
  // Parse as local date to avoid UTC offset shifting the day
  const parts = iso.split("T")[0].split("-");
  const year = parseInt(parts[0], 10);
  const month = parseInt(parts[1], 10) - 1; // 0-indexed
  const day = parseInt(parts[2], 10);
  return `${day} ${MONTHS[month]} ${year}`;
}

/**
 * formatDateTime("2026-05-31T14:23:00") → "31 may 2026, 14:23"
 * Used for the "Creado" field in GastoDetailPage.
 */
export function formatDateTime(iso: string): string {
  const datePart = formatDate(iso);
  // Extract HH:MM from the time component
  const timePart = iso.split("T")[1];
  if (!timePart) return datePart;
  const hhmm = timePart.substring(0, 5);
  return `${datePart}, ${hhmm}`;
}
