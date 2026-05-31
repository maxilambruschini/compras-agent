/**
 * CierresListPage — Read-only list of caja cierres.
 * Columns: Fecha, Cierre (hora_cierre), Efectivo en caja (right-aligned), Registrado por.
 * Rows are NOT clickable. No edit/delete controls.
 * UI-SPEC §Table (static-rows), §Cierres table columns.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatARS } from "../utils/formatARS";
import { formatDate } from "../utils/formatDate";
import Spinner from "../components/Spinner";

export default function CierresListPage() {
  const { data, isPending, error } = useQuery({
    queryKey: ["cierres"],
    queryFn: () => api.listCierres(),
    staleTime: 30_000,
  });

  return (
    <div className="page-content">
      <h1 className="page-title">Cierres de Caja</h1>

      {/* Loading state */}
      {isPending && <Spinner />}

      {/* Error state */}
      {error && !isPending && (
        <div className="error-banner" role="alert">
          <p className="error-banner-heading">No se pudo cargar la información</p>
          <p className="error-banner-body">
            Ocurrió un error al conectar con el servidor. Recargá la página para reintentar.
          </p>
        </div>
      )}

      {/* Empty state */}
      {!isPending && !error && data && data.length === 0 && (
        <div className="empty-state">
          <p className="empty-state-heading">No hay cierres registrados</p>
          <p className="empty-state-body">
            Los cierres de caja reportados por WhatsApp aparecerán aquí.
          </p>
        </div>
      )}

      {/* Table — rows are NOT clickable (static-rows class) */}
      {!isPending && !error && data && data.length > 0 && (
        <div className="table-wrapper">
          <table className="data-table static-rows">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Cierre</th>
                <th className="col-right">Efectivo en caja</th>
                <th className="col-sender">Registrado por</th>
              </tr>
            </thead>
            <tbody>
              {data.map((cierre) => (
                <tr key={cierre.id}>
                  <td>{formatDate(cierre.fecha)}</td>
                  <td>{cierre.hora_cierre}</td>
                  <td className="col-right">{formatARS(cierre.efectivo_en_caja)}</td>
                  <td className="col-sender">{cierre.sender_phone}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
