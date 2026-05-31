/**
 * GastosListPage — Filterable/searchable list of committed gastos.
 * Columns: Fecha, Concepto, Monto (right-aligned), Ticket (badge), Registrado por.
 * Row click → /gastos/:id. Filter bar: Desde, Hasta, Buscar + Limpiar.
 * UI-SPEC §Table, §Filter Bar, §Monto Display, §Ticket Indicator.
 */
import { useState } from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatARS } from "../utils/formatARS";
import { formatDate } from "../utils/formatDate";
import Spinner from "../components/Spinner";

export default function GastosListPage() {
  const navigate = useNavigate();
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [buscar, setBuscar] = useState("");

  const hasFilter = Boolean(desde || hasta || buscar);

  const { data, isPending, error } = useQuery({
    queryKey: ["gastos", { from: desde, to: hasta, q: buscar }],
    queryFn: () =>
      api.listGastos({
        from: desde || undefined,
        to: hasta || undefined,
        q: buscar || undefined,
      }),
    staleTime: 30_000,
  });

  function handleLimpiar() {
    setDesde("");
    setHasta("");
    setBuscar("");
  }

  return (
    <div className="page-content">
      <h1 className="page-title">Gastos</h1>

      {/* Filter bar */}
      <div className="filter-bar">
        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-desde">
            Desde
          </label>
          <input
            id="filter-desde"
            type="date"
            className="filter-input"
            value={desde}
            onChange={(e) => setDesde(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-hasta">
            Hasta
          </label>
          <input
            id="filter-hasta"
            type="date"
            className="filter-input"
            value={hasta}
            onChange={(e) => setHasta(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label className="filter-label" htmlFor="filter-buscar">
            Buscar
          </label>
          <input
            id="filter-buscar"
            type="text"
            className="filter-input"
            placeholder="Buscar concepto..."
            value={buscar}
            onChange={(e) => setBuscar(e.target.value)}
          />
        </div>

        <button
          type="button"
          className="filter-clear"
          onClick={handleLimpiar}
        >
          Limpiar
        </button>
      </div>

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
          {hasFilter ? (
            <>
              <p className="empty-state-heading">Sin resultados</p>
              <p className="empty-state-body">
                Ningún gasto coincide con los filtros aplicados. Probá con otro rango de fechas o concepto.
              </p>
            </>
          ) : (
            <>
              <p className="empty-state-heading">No hay gastos registrados</p>
              <p className="empty-state-body">
                Los gastos capturados por WhatsApp aparecerán aquí.
              </p>
            </>
          )}
        </div>
      )}

      {/* Table */}
      {!isPending && !error && data && data.length > 0 && (
        <div className="table-wrapper">
          <table className="data-table clickable-rows">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Concepto</th>
                <th className="col-right">Monto</th>
                <th className="col-shrink">Ticket</th>
                <th className="col-sender">Registrado por</th>
              </tr>
            </thead>
            <tbody>
              {data.map((gasto) => (
                <tr
                  key={gasto.id}
                  onClick={() => navigate(`/gastos/${gasto.id}`)}
                >
                  <td>{formatDate(gasto.fecha)}</td>
                  <td>{gasto.concepto}</td>
                  <td className="col-right">{formatARS(gasto.monto)}</td>
                  <td className="col-shrink">
                    {gasto.ticket_image_path ? (
                      <span className="ticket-badge">con ticket</span>
                    ) : (
                      <span className="ticket-none">—</span>
                    )}
                  </td>
                  <td className="col-sender">{gasto.sender_phone}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
