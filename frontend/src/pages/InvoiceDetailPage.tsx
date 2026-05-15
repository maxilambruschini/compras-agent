import { useState } from "react";
import { useParams } from "react-router";
import { useInvoice } from "../hooks/useInvoice";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import InvoiceHeader from "../components/InvoiceHeader";
import ActionBar from "../components/ActionBar";
import DeleteConfirmation from "../components/DeleteConfirmation";
import LineItemsTable from "../components/LineItemsTable";
import ImagePanel from "../components/ImagePanel";
import EditDocumentModal from "../components/EditDocumentModal";

export default function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isPending, error } = useInvoice(id ?? "");

  const [showEditModal, setShowEditModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  if (isPending) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-white p-4 md:p-6">
        <ErrorBanner message="No se pudo cargar la factura. Verificá la conexión con el servidor e intentá nuevamente." />
      </div>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <div className="min-h-screen bg-white">
      <main className="p-4 md:p-6 grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* Left column: data */}
        <div className="flex flex-col gap-6">
          <InvoiceHeader invoice={data} onEditClick={() => setShowEditModal(true)} />
          <ActionBar
            id={data.id}
            status={data.status}
            onDeleteClick={() => setShowDeleteConfirm(true)}
          />
          {showDeleteConfirm && (
            <DeleteConfirmation
              id={data.id}
              onCancel={() => setShowDeleteConfirm(false)}
            />
          )}
          <LineItemsTable invoiceId={data.id} items={data.line_items} />
        </div>

        {/* Right column: image */}
        <div className="md:sticky md:top-6">
          <ImagePanel
            invoiceId={data.id}
            imagePath={data.image_path}
            proveedor={data.proveedor}
            numeroDocumento={data.numero_documento}
          />
        </div>
      </main>

      <EditDocumentModal
        open={showEditModal}
        onOpenChange={setShowEditModal}
        invoice={data}
      />
    </div>
  );
}
