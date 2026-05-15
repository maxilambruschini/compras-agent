import { useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import LoadingSpinner from "./LoadingSpinner";
import ErrorBanner from "./ErrorBanner";
import { deleteInvoice } from "../lib/api";

interface DeleteConfirmationProps {
  id: string;
  onCancel: () => void;
}

export default function DeleteConfirmation({ id, onCancel }: DeleteConfirmationProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const deleteMutation = useMutation({
    mutationFn: () => deleteInvoice(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
      navigate("/");
    },
    onError: () => {
      setDeleteError("No se pudo eliminar la factura. Intentá nuevamente.");
    },
  });

  return (
    <div className="border border-red-200 rounded-lg p-4 bg-red-50 flex flex-col gap-3">
      <p className="font-semibold text-red-800">¿Eliminar esta factura?</p>
      <p id="delete-confirm-body" className="text-sm text-red-700">
        Se eliminará el registro de la base de datos. El archivo original se conserva.
      </p>
      <div className="flex gap-2">
        <Button
          variant="destructive"
          onClick={() => deleteMutation.mutate()}
          disabled={deleteMutation.isPending}
          aria-describedby="delete-confirm-body"
          className="min-h-[44px]"
        >
          {deleteMutation.isPending && <LoadingSpinner />}
          Sí, eliminar
        </Button>
        <Button
          variant="ghost"
          onClick={onCancel}
          disabled={deleteMutation.isPending}
          className="min-h-[44px]"
        >
          Cancelar
        </Button>
      </div>
      {deleteError && <ErrorBanner message={deleteError} />}
    </div>
  );
}
