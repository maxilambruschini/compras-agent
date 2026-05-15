import { useQuery } from "@tanstack/react-query";
import { fetchInvoices } from "../lib/api";
import type { InvoiceListParams } from "../types/invoice";

export function useInvoices(params: InvoiceListParams) {
  return useQuery({
    queryKey: ["invoices", params],
    queryFn: () => fetchInvoices(params),
  });
}
