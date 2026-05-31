/**
 * GastoDetailPage — Full detail view for a single gasto.
 * Fields: Fecha, Concepto, Monto, Ticket, Registrado por, Creado.
 * Ticket image inline (click → new tab) or "Sin ticket adjunto".
 * UI-SPEC §Detail Page Layout, §Ticket Image.
 */
import { useParams, Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatARS } from "../utils/formatARS";
import { formatDate, formatDateTime } from "../utils/formatDate";
import Spinner from "../components/Spinner";

export default function GastoDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data: gasto, isPending, error } = useQuery({
    queryKey: ["gastos", id],
    queryFn: () => api.getGasto(id!),
    staleTime: 30_000,
    enabled: Boolean(id),
  });

  const ticketUrl = id ? api.ticketUrl(id) : null;

  return (
    <div className="page-content">
      <Link to="/gastos" className="detail-back-link">
        ← Volver a gastos
      </Link>

      <h1 className="page-title">Detalle de Gasto</h1>

      {/* Loading state */}
      {isPending && <Spinner />}

      {/* Error state (includes 404) */}
      {error && !isPending && (
        <div className="error-banner" role="alert">
          <p className="error-banner-heading">No se pudo cargar la información</p>
          <p className="error-banner-body">
            Ocurrió un error al conectar con el servidor. Recargá la página para reintentar.
          </p>
        </div>
      )}

      {/* Detail content */}
      {!isPending && !error && gasto && (
        <>
          <dl className="detail-dl">
            <dt>Fecha</dt>
            <dd>{formatDate(gasto.fecha)}</dd>

            <dt>Concepto</dt>
            <dd>{gasto.concepto}</dd>

            <dt>Monto</dt>
            <dd>{formatARS(gasto.monto)}</dd>

            <dt>Ticket</dt>
            <dd>
              {gasto.ticket_image_path ? (
                <span className="ticket-badge">con ticket</span>
              ) : (
                <span className="ticket-none">—</span>
              )}
            </dd>

            <dt>Registrado por</dt>
            <dd>{gasto.sender_phone}</dd>

            <dt>Creado</dt>
            <dd>{formatDateTime(gasto.created_at)}</dd>
          </dl>

          {/* Ticket image section */}
          <div className="ticket-section">
            {gasto.ticket_image_path && ticketUrl ? (
              <>
                <p className="ticket-section-title">Imagen del ticket</p>
                <img
                  src={ticketUrl}
                  alt="Ticket de gasto"
                  className="ticket-image"
                  onClick={() => window.open(ticketUrl, "_blank", "noopener,noreferrer")}
                />
              </>
            ) : (
              <p className="ticket-absent">Sin ticket adjunto</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
