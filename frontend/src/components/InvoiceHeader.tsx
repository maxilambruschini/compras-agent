import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import StatusBadge from "./StatusBadge";
import { formatDate, formatCuit } from "../lib/format";
import type { InvoiceDetailResponse } from "../types/invoice";

interface InvoiceHeaderProps {
  invoice: InvoiceDetailResponse;
  onEditClick: () => void;
}

export default function InvoiceHeader({ invoice, onEditClick }: InvoiceHeaderProps) {
  return (
    <div className="flex flex-col gap-3">
      <Link to="/" className="text-sm text-blue-600">
        ← Volver a la lista
      </Link>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Encabezado</h2>
        <Button variant="outline" size="sm" onClick={onEditClick} className="min-h-[44px]">
          Editar documento
        </Button>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-gray-500 text-xs font-semibold uppercase">Proveedor</dt>
        <dd className="text-gray-900">{invoice.proveedor ?? "—"}</dd>

        <dt className="text-gray-500 text-xs font-semibold uppercase">Tipo comprobante</dt>
        <dd className="text-gray-900">{invoice.tipo_comprobante ?? "—"}</dd>

        <dt className="text-gray-500 text-xs font-semibold uppercase">Número</dt>
        <dd className="text-gray-900">{invoice.numero_documento ?? "—"}</dd>

        <dt className="text-gray-500 text-xs font-semibold uppercase">Fecha</dt>
        <dd className="text-gray-900">{formatDate(invoice.fecha)}</dd>

        <dt className="text-gray-500 text-xs font-semibold uppercase">CUIT proveedor</dt>
        <dd className="text-gray-900">{formatCuit(invoice.cuit_proveedor)}</dd>

        <dt className="text-gray-500 text-xs font-semibold uppercase">CAE</dt>
        <dd className="text-gray-900">{invoice.cae ?? "—"}</dd>

        <dt className="text-gray-500 text-xs font-semibold uppercase">Vencimiento CAE</dt>
        <dd className="text-gray-900">{formatDate(invoice.fecha_vencimiento_cae)}</dd>

        <dt className="text-gray-500 text-xs font-semibold uppercase">Estado</dt>
        <dd className="text-gray-900">
          <StatusBadge status={invoice.status} />
        </dd>

        <dt className="text-gray-500 text-xs font-semibold uppercase">Confianza</dt>
        <dd className="text-gray-900">
          {invoice.confidence_score
            ? `${(Number(invoice.confidence_score) * 100).toFixed(0)}%`
            : "—"}
        </dd>
      </dl>
    </div>
  );
}
