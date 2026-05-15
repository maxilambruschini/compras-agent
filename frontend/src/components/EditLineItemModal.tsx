import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import FormField from "./FormField";
import ErrorBanner from "./ErrorBanner";
import LoadingSpinner from "./LoadingSpinner";
import { patchLineItem } from "../lib/api";
import type { LineItemResponse, LineItemPatch } from "../types/invoice";

interface EditLineItemModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  invoiceId: string;
  item: LineItemResponse;
}

export default function EditLineItemModal({
  open,
  onOpenChange,
  invoiceId,
  item,
}: EditLineItemModalProps) {
  const queryClient = useQueryClient();
  const [saveError, setSaveError] = useState<string | null>(null);

  const [descripcion, setDescripcion] = useState(item.descripcion ?? "");
  const [codigo_sku, setCodigoSku] = useState(item.codigo_sku ?? "");
  const [bultos, setBultos] = useState(item.bultos ?? "");
  const [unidades_por_bulto, setUnidadesPorBulto] = useState(item.unidades_por_bulto ?? "");
  const [precio_unitario_sin_iva, setPrecioUnitario] = useState(
    item.precio_unitario_sin_iva ?? ""
  );
  const [descuento_pct, setDescuentoPct] = useState(item.descuento_pct ?? "");
  const [iva_rate, setIvaRate] = useState(item.iva_rate ?? "");
  const [percepciones_iibb, setPercepcionesIibb] = useState(item.percepciones_iibb ?? "");

  const mutation = useMutation({
    mutationFn: (data: LineItemPatch) => patchLineItem(invoiceId, item.id, data),
    onSuccess: () => {
      setSaveError(null);
      queryClient.invalidateQueries({ queryKey: ["invoice", invoiceId] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      onOpenChange(false);
    },
    onError: () => {
      setSaveError("No se pudo guardar. Intentá nuevamente.");
    },
  });

  function handleSave() {
    mutation.mutate({
      descripcion: descripcion || null,
      codigo_sku: codigo_sku || null,
      bultos: bultos || null,
      unidades_por_bulto: unidades_por_bulto || null,
      precio_unitario_sin_iva: precio_unitario_sin_iva || null,
      descuento_pct: descuento_pct || null,
      iva_rate: iva_rate || null,
      percepciones_iibb: percepciones_iibb || null,
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full mx-4 md:max-w-[640px]">
        <DialogHeader>
          <DialogTitle>Editar ítem</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-4">
          <FormField label="Descripción" htmlFor="descripcion">
            <Input
              id="descripcion"
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
            />
          </FormField>
          <FormField label="Código SKU" htmlFor="codigo_sku">
            <Input
              id="codigo_sku"
              value={codigo_sku}
              onChange={(e) => setCodigoSku(e.target.value)}
            />
          </FormField>
          <FormField label="Bultos" htmlFor="bultos">
            <Input
              id="bultos"
              type="number"
              step="0.0001"
              value={bultos}
              onChange={(e) => setBultos(e.target.value)}
            />
          </FormField>
          <FormField label="Unidades por bulto" htmlFor="unidades_por_bulto">
            <Input
              id="unidades_por_bulto"
              type="number"
              step="0.0001"
              value={unidades_por_bulto}
              onChange={(e) => setUnidadesPorBulto(e.target.value)}
            />
          </FormField>
          <FormField label="Precio unit. s/IVA" htmlFor="precio_unitario_sin_iva">
            <Input
              id="precio_unitario_sin_iva"
              type="number"
              step="0.0001"
              value={precio_unitario_sin_iva}
              onChange={(e) => setPrecioUnitario(e.target.value)}
            />
          </FormField>
          <FormField label="Descuento %" htmlFor="descuento_pct">
            <Input
              id="descuento_pct"
              type="number"
              step="0.01"
              placeholder="0 a 1 — ej: 0.10 = 10%"
              value={descuento_pct}
              onChange={(e) => setDescuentoPct(e.target.value)}
            />
          </FormField>
          <FormField label="IVA rate" htmlFor="iva_rate">
            <Input
              id="iva_rate"
              type="number"
              step="0.005"
              placeholder="0, 0.105, o 0.21"
              value={iva_rate}
              onChange={(e) => setIvaRate(e.target.value)}
            />
          </FormField>
          <FormField label="Percepciones IIBB" htmlFor="percepciones_iibb">
            <Input
              id="percepciones_iibb"
              type="number"
              step="0.0001"
              value={percepciones_iibb}
              onChange={(e) => setPercepcionesIibb(e.target.value)}
            />
          </FormField>
        </div>
        <div className="flex flex-col gap-2">
          {saveError && <ErrorBanner message={saveError} />}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button onClick={handleSave} disabled={mutation.isPending} className="min-h-[44px]">
              {mutation.isPending && <LoadingSpinner />}
              Guardar cambios
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
