import type {
  InvoiceListParams,
  InvoiceListResponse,
  InvoiceDetailResponse,
  InvoiceDocumentPatch,
  LineItemPatch,
  LineItemResponse,
} from "../types/invoice";

// All API calls are prefixed with /api so the Vite dev server proxy can
// distinguish them from React Router page routes (e.g. /invoices/:id).
// The proxy strips /api before forwarding to the backend.
const BASE_URL = import.meta.env.VITE_API_URL ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail: string;
    try {
      const json = await res.json();
      detail = json.detail ?? `HTTP ${res.status}`;
    } catch {
      detail = `HTTP ${res.status}`;
    }
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

export function fetchInvoices(params: InvoiceListParams): Promise<InvoiceListResponse> {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      searchParams.set(key, String(value));
    }
  }
  const qs = searchParams.toString();
  return request<InvoiceListResponse>(`/invoices${qs ? `?${qs}` : ""}`);
}

export function fetchInvoice(id: string): Promise<InvoiceDetailResponse> {
  return request<InvoiceDetailResponse>(`/invoices/${id}`);
}

export function patchInvoice(
  id: string,
  data: Partial<InvoiceDocumentPatch>
): Promise<InvoiceDetailResponse> {
  return request<InvoiceDetailResponse>(`/invoices/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function patchInvoiceStatus(
  id: string,
  status: "confirmed" | "rejected"
): Promise<InvoiceDetailResponse> {
  return request<InvoiceDetailResponse>(`/invoices/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function patchLineItem(
  id: string,
  itemId: number,
  data: Partial<LineItemPatch>
): Promise<LineItemResponse> {
  return request<LineItemResponse>(`/invoices/${id}/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteInvoice(id: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/invoices/${id}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) {
    let detail: string;
    try {
      const json = await res.json();
      detail = json.detail ?? `HTTP ${res.status}`;
    } catch {
      detail = `HTTP ${res.status}`;
    }
    throw new Error(detail);
  }
  // 204 No Content — no body to parse
}

export function imageUrl(invoiceId: string): string {
  return `${BASE_URL}/invoices/${invoiceId}/image`;
}
