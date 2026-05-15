import { imageUrl } from "../lib/api";

interface ImagePanelProps {
  invoiceId: string;
  imagePath: string | null;
  proveedor: string | null;
  numeroDocumento: string | null;
}

export default function ImagePanel({ invoiceId, imagePath, proveedor, numeroDocumento }: ImagePanelProps) {
  if (!imagePath) {
    return (
      <div className="md:sticky md:top-6">
        <div className="flex items-center justify-center h-64 bg-gray-100 text-gray-500 rounded">
          Sin imagen
        </div>
      </div>
    );
  }

  const extension = imagePath.split(".").pop()?.toLowerCase();

  return (
    <div className="md:sticky md:top-6">
      {extension === "pdf" ? (
        <embed
          src={imageUrl(invoiceId)}
          type="application/pdf"
          className="w-full max-h-[80vh]"
        />
      ) : (
        <img
          src={imageUrl(invoiceId)}
          alt={`Factura original de ${proveedor ?? "proveedor"} — ${numeroDocumento ?? "sin número"}`}
          className="w-full max-h-[80vh] object-contain rounded border border-gray-200"
        />
      )}
    </div>
  );
}
