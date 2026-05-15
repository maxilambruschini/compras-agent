import { useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import EditLineItemModal from "./EditLineItemModal";
import { formatCurrency } from "../lib/format";
import type { LineItemResponse } from "../types/invoice";

interface LineItemsTableProps {
  invoiceId: string;
  items: LineItemResponse[];
}

export default function LineItemsTable({ invoiceId, items }: LineItemsTableProps) {
  const [editingItem, setEditingItem] = useState<LineItemResponse | null>(null);

  const fmt = (v: string | null) =>
    !v || parseFloat(v) === 0
      ? "—"
      : parseFloat(v)
          .toLocaleString("es-AR", { maximumFractionDigits: 4 })
          .replace(/\.?0+$/, "");

  function formatPercent(value: string | null, decimals: number): string {
    if (!value) return "—";
    const num = Number(value);
    if (isNaN(num)) return "—";
    return `${(num * 100).toFixed(decimals)}%`;
  }

  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">Ítems</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>#</TableHead>
            <TableHead>Descripción</TableHead>
            <TableHead>SKU</TableHead>
            <TableHead>Bultos</TableHead>
            <TableHead>U/Bulto</TableHead>
            <TableHead>P.Unit. s/IVA</TableHead>
            <TableHead>Dto%</TableHead>
            <TableHead>IVA%</TableHead>
            <TableHead>Percepciones</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={10} className="text-center text-gray-500 py-4">
                Sin ítems registrados
              </TableCell>
            </TableRow>
          ) : (
            items.map((item, index) => (
              <TableRow key={item.id}>
                <TableCell>{index + 1}</TableCell>
                <TableCell>{item.descripcion ?? "—"}</TableCell>
                <TableCell>{item.codigo_sku ?? "—"}</TableCell>
                <TableCell>{fmt(item.bultos)}</TableCell>
                <TableCell>{fmt(item.unidades_por_bulto)}</TableCell>
                <TableCell>{formatCurrency(item.precio_unitario_sin_iva)}</TableCell>
                <TableCell>{formatPercent(item.descuento_pct, 1)}</TableCell>
                <TableCell>{formatPercent(item.iva_rate, 0)}</TableCell>
                <TableCell>{formatCurrency(item.percepciones_iibb)}</TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="min-h-[44px]"
                    onClick={() => setEditingItem(item)}
                  >
                    Editar
                  </Button>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      {editingItem && (
        <EditLineItemModal
          open={true}
          onOpenChange={(open) => { if (!open) setEditingItem(null); }}
          invoiceId={invoiceId}
          item={editingItem}
        />
      )}
    </div>
  );
}
