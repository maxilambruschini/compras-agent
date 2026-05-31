/**
 * Typed fetch API client.
 * BASE reads from import.meta.env.VITE_API_URL; falls back to "/api" (Vite dev proxy).
 * All endpoints include the /api prefix — matches backend mount (prefix="/api").
 */

// TypeScript types matching the backend Pydantic response models.
// Decimal fields (monto, efectivo_en_caja) arrive as STRINGS from Pydantic v2.

export interface GastoOut {
  id: string;
  fecha: string;          // ISO date "2026-05-31"
  concepto: string;
  monto: string;          // Decimal serialized as string, e.g. "1234.56"
  ticket_image_path: string | null;
  sender_phone: string;
  created_at: string;     // ISO datetime
}

export interface CierreOut {
  id: string;
  fecha: string;          // ISO date
  hora_cierre: string;    // "12:00" | "17:00"
  efectivo_en_caja: string; // Decimal as string
  sender_phone: string;
  created_at: string;     // ISO datetime
}

const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  listGastos: (params?: { from?: string; to?: string; q?: string }) => {
    const entries = Object.entries(params ?? {}).filter(
      ([, v]) => v !== undefined && v !== ""
    ) as [string, string][];
    const qs = new URLSearchParams(entries).toString();
    return get<GastoOut[]>(`/gastos${qs ? `?${qs}` : ""}`);
  },

  getGasto: (id: string) => get<GastoOut>(`/gastos/${id}`),

  ticketUrl: (id: string) => `${BASE}/gastos/${id}/ticket`,

  listCierres: () => get<CierreOut[]>("/cierres"),
};
