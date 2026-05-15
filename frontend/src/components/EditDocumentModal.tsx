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
import { patchInvoice } from "../lib/api";
import type { InvoiceDetailResponse, InvoiceDocumentPatch } from "../types/invoice";

interface EditDocumentModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  invoice: InvoiceDetailResponse;
}

export default function EditDocumentModal({
  open,
  onOpenChange,
  invoice,
}: EditDocumentModalProps) {
  const queryClient = useQueryClient();
  const [saveError, setSaveError] = useState<string | null>(null);

  const [tipo_comprobante, setTipoComprobante] = useState(invoice.tipo_comprobante ?? "");
  const [numero_documento, setNumeroDocumento] = useState(invoice.numero_documento ?? "");
  const [proveedor, setProveedor] = useState(invoice.proveedor ?? "");
  const [fecha, setFecha] = useState(invoice.fecha ?? "");
  const [cuit_proveedor, setCuitProveedor] = useState(invoice.cuit_proveedor ?? "");
  const [cae, setCae] = useState(invoice.cae ?? "");
  const [fecha_vencimiento_cae, setFechaVencimientoCae] = useState(
    invoice.fecha_vencimiento_cae ?? ""
  );

  const mutation = useMutation({
    mutationFn: (data: InvoiceDocumentPatch) => patchInvoice(invoice.id, data),
    onSuccess: () => {
      setSaveError(null);
      queryClient.invalidateQueries({ queryKey: ["invoice", invoice.id] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      onOpenChange(false);
    },
    onError: () => {
      setSaveError("No se pudo guardar. Intentá nuevamente.");
    },
  });

  function handleSave() {
    mutation.mutate({
      tipo_comprobante: tipo_comprobante || null,
      numero_documento: numero_documento || null,
      proveedor: proveedor || null,
      fecha: fecha || null,
      cuit_proveedor: cuit_proveedor || null,
      cae: cae || null,
      fecha_vencimiento_cae: fecha_vencimiento_cae || null,
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full mx-4 md:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>Editar documento</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-4">
          <FormField label="Proveedor" htmlFor="proveedor">
            <Input
              id="proveedor"
              value={proveedor}
              onChange={(e) => setProveedor(e.target.value)}
            />
          </FormField>
          <FormField label="Tipo comprobante" htmlFor="tipo_comprobante">
            <Input
              id="tipo_comprobante"
              value={tipo_comprobante}
              onChange={(e) => setTipoComprobante(e.target.value)}
            />
          </FormField>
          <FormField label="Número" htmlFor="numero_documento">
            <Input
              id="numero_documento"
              value={numero_documento}
              onChange={(e) => setNumeroDocumento(e.target.value)}
            />
          </FormField>
          <FormField label="Fecha" htmlFor="fecha">
            <Input
              id="fecha"
              type="date"
              value={fecha}
              onChange={(e) => setFecha(e.target.value)}
            />
          </FormField>
          <FormField label="CUIT proveedor" htmlFor="cuit_proveedor">
            <Input
              id="cuit_proveedor"
              value={cuit_proveedor}
              onChange={(e) => setCuitProveedor(e.target.value)}
            />
          </FormField>
          <FormField label="CAE" htmlFor="cae">
            <Input
              id="cae"
              value={cae}
              onChange={(e) => setCae(e.target.value)}
            />
          </FormField>
          <FormField label="Vencimiento CAE" htmlFor="fecha_vencimiento_cae">
            <Input
              id="fecha_vencimiento_cae"
              type="date"
              value={fecha_vencimiento_cae}
              onChange={(e) => setFechaVencimientoCae(e.target.value)}
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
