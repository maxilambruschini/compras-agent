/**
 * formatARS — Manual Argentine peso formatter.
 * Produces $1.234,56 format (thousands ".", decimal ",", 2 decimal places).
 * Does NOT use Intl.NumberFormat or locale string APIs (inconsistent mobile support).
 * UI-SPEC §Monto Display.
 */
export function formatARS(value: string | number): string {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(num)) return "—";
  const [intPart, decPart = "00"] = num.toFixed(2).split(".");
  const intFormatted = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `$${intFormatted},${decPart}`;
}
