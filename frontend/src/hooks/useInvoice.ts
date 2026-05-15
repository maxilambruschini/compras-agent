import { useQuery } from "@tanstack/react-query";
import { fetchInvoice } from "../lib/api";

export function useInvoice(id: string) {
  return useQuery({
    queryKey: ["invoice", id],
    queryFn: () => fetchInvoice(id),
    enabled: !!id,
  });
}
