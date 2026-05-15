import { useNavigate } from "react-router";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import StatusBadge from "./StatusBadge";
import { formatDate } from "../lib/format";
import type { InvoiceListItem } from "../types/invoice";

interface InvoiceTableProps {
  invoices: InvoiceListItem[];
}

export default function InvoiceTable({ invoices }: InvoiceTableProps) {
  const navigate = useNavigate();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Proveedor</TableHead>
          <TableHead className="hidden md:table-cell">Tipo</TableHead>
          <TableHead className="hidden md:table-cell">Número</TableHead>
          <TableHead className="hidden md:table-cell">Fecha</TableHead>
          <TableHead>Estado</TableHead>
          <TableHead>Creado</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {invoices.length === 0 ? (
          <TableRow>
            <TableCell colSpan={6} className="text-center py-12">
              <div className="flex flex-col items-center gap-2">
                <p className="text-lg font-medium text-gray-700">Sin facturas</p>
                <p className="text-sm text-gray-500">
                  No se encontraron facturas con los filtros aplicados. Ajustá los filtros o esperá nuevas capturas por WhatsApp.
                </p>
              </div>
            </TableCell>
          </TableRow>
        ) : (
          invoices.map((invoice) => (
            <TableRow
              key={invoice.id}
              className={invoice.status === "pending_review" ? "bg-amber-50 cursor-pointer hover:bg-amber-100" : "cursor-pointer hover:bg-gray-50"}
              onClick={() => navigate("/invoices/" + invoice.id)}
            >
              <TableCell className="font-medium">
                {invoice.proveedor ?? "—"}
              </TableCell>
              <TableCell className="hidden md:table-cell">
                {invoice.tipo_comprobante ?? "—"}
              </TableCell>
              <TableCell className="hidden md:table-cell">
                {invoice.numero_documento ?? "—"}
              </TableCell>
              <TableCell className="hidden md:table-cell">
                {formatDate(invoice.fecha)}
              </TableCell>
              <TableCell>
                <StatusBadge status={invoice.status} />
              </TableCell>
              <TableCell>
                {formatDate(invoice.created_at.split("T")[0])}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
