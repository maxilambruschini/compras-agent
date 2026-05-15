/**
 * TypeScript interfaces matching backend API response shapes exactly.
 * Backend serializes uuid.UUID fields as UUID-formatted strings in JSON.
 */

/** Branded UUID string type — format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx */
export type InvoiceId = string; // UUID string — format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

export interface LineItemResponse {
  id: number;
  invoice_id: InvoiceId;
  descripcion: string | null;
  codigo_sku: string | null;
  bultos: string | null;
  unidades_por_bulto: string | null;
  precio_unitario_sin_iva: string | null;
  descuento_pct: string | null;
  iva_rate: string | null;
  percepciones_iibb: string | null;
}

export interface InvoiceListItem {
  id: InvoiceId;
  tipo_comprobante: string | null;
  numero_documento: string | null;
  proveedor: string | null;
  fecha: string | null;
  status: string;
  confidence_score: string | null;
  created_at: string;
}

export interface InvoiceDetailResponse extends InvoiceListItem {
  cuit_proveedor: string | null;
  cae: string | null;
  fecha_vencimiento_cae: string | null;
  image_path: string | null;
  updated_at: string;
  line_items: LineItemResponse[];
}

export interface InvoiceListResponse {
  items: InvoiceListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface InvoiceListParams {
  page?: number;
  page_size?: number;
  status?: string;
  proveedor?: string;
  fecha_from?: string;
  fecha_to?: string;
  q?: string;
}

export interface InvoiceDocumentPatch {
  tipo_comprobante?: string | null;
  numero_documento?: string | null;
  proveedor?: string | null;
  fecha?: string | null;
  cuit_proveedor?: string | null;
  cae?: string | null;
  fecha_vencimiento_cae?: string | null;
}

export interface LineItemPatch {
  descripcion?: string | null;
  codigo_sku?: string | null;
  bultos?: string | null;
  unidades_por_bulto?: string | null;
  precio_unitario_sin_iva?: string | null;
  descuento_pct?: string | null;
  iva_rate?: string | null;
  percepciones_iibb?: string | null;
}
