import { BrowserRouter, Routes, Route } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import InvoiceListPage from "./pages/InvoiceListPage";
import InvoiceDetailPage from "./pages/InvoiceDetailPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<InvoiceListPage />} />
          <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
