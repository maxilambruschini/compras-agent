/**
 * Spinner — CSS-ring loading indicator.
 * Centered in content area with "Cargando..." label.
 * UI-SPEC §Loading State.
 */
export default function Spinner() {
  return (
    <div className="spinner-container">
      <div className="spinner-ring" aria-label="Cargando" />
      <span>Cargando...</span>
    </div>
  );
}
