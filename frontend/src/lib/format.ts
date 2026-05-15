/**
 * Argentine locale formatters for invoice display.
 */

/**
 * Format a currency value in Argentine pesos (ARS).
 * Returns "—" for null/undefined/NaN values.
 * Example: 1234.56 → "$ 1.234,56"
 */
export function formatCurrency(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const num = Number(value);
  if (isNaN(num)) return "—";
  return "$ " + num.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * Format an ISO date string (YYYY-MM-DD) to Argentine format (DD/MM/AAAA).
 * Returns "—" for null/undefined/empty values.
 * Example: "2026-05-14" → "14/05/2026"
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return "—";
  return `${d}/${m}/${y}`;
}

/**
 * Format a CUIT string for display.
 * CUITs are already stored correctly (XX-XXXXXXXX-X format).
 * Returns "—" for null/undefined.
 */
export function formatCuit(cuit: string | null | undefined): string {
  if (!cuit) return "—";
  return cuit;
}
