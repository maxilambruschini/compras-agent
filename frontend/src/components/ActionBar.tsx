import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import LoadingSpinner from "./LoadingSpinner";
import ErrorBanner from "./ErrorBanner";
import { patchInvoiceStatus } from "../lib/api";

interface ActionBarProps {
  id: string;
  status: string;
  onDeleteClick: () => void;
}

export default function ActionBar({ id, status, onDeleteClick }: ActionBarProps) {
  const queryClient = useQueryClient();
  const [statusError, setStatusError] = useState<string | null>(null);

  const confirmMutation = useMutation({
    mutationFn: () => patchInvoiceStatus(id, "confirmed"),
    onSuccess: () => {
      setStatusError(null);
      queryClient.invalidateQueries({ queryKey: ["invoice", id] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
    onError: () => {
      setStatusError("No se pudo actualizar el estado. Intentá nuevamente.");
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () => patchInvoiceStatus(id, "rejected"),
    onSuccess: () => {
      setStatusError(null);
      queryClient.invalidateQueries({ queryKey: ["invoice", id] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
    onError: () => {
      setStatusError("No se pudo actualizar el estado. Intentá nuevamente.");
    },
  });

  return (
    <div className="flex flex-col gap-3 py-4">
      <div className="flex flex-col md:flex-row gap-2 md:gap-3">
        {status === "pending_review" && (
          <>
            <Button
              onClick={() => confirmMutation.mutate()}
              disabled={confirmMutation.isPending || rejectMutation.isPending}
              className="w-full md:w-auto min-h-[44px]"
            >
              {confirmMutation.isPending && <LoadingSpinner />}
              Confirmar
            </Button>
            <Button
              variant="outline"
              onClick={() => rejectMutation.mutate()}
              disabled={confirmMutation.isPending || rejectMutation.isPending}
              className="w-full md:w-auto min-h-[44px]"
            >
              {rejectMutation.isPending && <LoadingSpinner />}
              Rechazar
            </Button>
          </>
        )}
        <Button
          variant="destructive"
          onClick={onDeleteClick}
          className="w-full md:w-auto min-h-[44px]"
        >
          Eliminar factura
        </Button>
      </div>
      {statusError && <ErrorBanner message={statusError} />}
    </div>
  );
}
