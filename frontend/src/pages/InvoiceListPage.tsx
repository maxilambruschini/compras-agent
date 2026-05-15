import { useState } from "react";
import { useInvoices } from "../hooks/useInvoices";
import FilterToolbar from "../components/FilterToolbar";
import InvoiceTable from "../components/InvoiceTable";
import Pagination from "../components/Pagination";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import type { InvoiceListParams } from "../types/invoice";

export default function InvoiceListPage() {
  const [params, setParams] = useState<InvoiceListParams>({ page: 1, page_size: 20 });
  const { data, isPending, error } = useInvoices(params);

  return (
    <div className="min-h-screen bg-white">
      <header className="px-4 py-3 border-b flex items-center">
        <h1 className="text-xl font-semibold">Facturas</h1>
      </header>

      <FilterToolbar
        onFilter={(newParams) =>
          setParams({ ...newParams, page: 1, page_size: 20 })
        }
      />

      {isPending ? (
        <div className="flex items-center justify-center py-16">
          <LoadingSpinner />
        </div>
      ) : error ? (
        <div className="p-4">
          <ErrorBanner message="No se pudo cargar la lista de facturas. Verificá la conexión con el servidor e intentá nuevamente." />
        </div>
      ) : (
        <>
          <InvoiceTable invoices={data?.items ?? []} />
          <Pagination
            page={params.page ?? 1}
            pageSize={params.page_size ?? 20}
            total={data?.total ?? 0}
            onPageChange={(p) => setParams((prev) => ({ ...prev, page: p }))}
          />
        </>
      )}
    </div>
  );
}
