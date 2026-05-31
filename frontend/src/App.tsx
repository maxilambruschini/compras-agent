/**
 * App.tsx — Router + QueryClient wiring.
 * createBrowserRouter with layout route (NavTabs + Outlet).
 * "/" redirects to "/gastos".
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createBrowserRouter,
  RouterProvider,
  Navigate,
  Outlet,
} from "react-router";
import NavTabs from "./components/NavTabs";
import GastosListPage from "./pages/GastosListPage";
import GastoDetailPage from "./pages/GastoDetailPage";
import CierresListPage from "./pages/CierresListPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
    },
  },
});

function Layout() {
  return (
    <>
      <NavTabs />
      <Outlet />
    </>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/gastos" replace /> },
      { path: "/gastos", element: <GastosListPage /> },
      { path: "/gastos/:id", element: <GastoDetailPage /> },
      { path: "/cierres", element: <CierresListPage /> },
    ],
  },
]);

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
