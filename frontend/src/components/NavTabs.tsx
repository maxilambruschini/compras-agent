/**
 * NavTabs — Two-tab top navigation bar.
 * Tabs: "Gastos" | "Cierres de Caja"
 * Active tab: 2px solid var(--accent) bottom border + var(--text-h) color.
 * UI-SPEC §Layout / Navigation.
 */
import { NavLink } from "react-router";

export default function NavTabs() {
  return (
    <nav className="nav-bar" aria-label="Navegación principal">
      <NavLink
        to="/gastos"
        className={({ isActive }) =>
          isActive ? "nav-tab active" : "nav-tab"
        }
      >
        Gastos
      </NavLink>
      <NavLink
        to="/cierres"
        className={({ isActive }) =>
          isActive ? "nav-tab active" : "nav-tab"
        }
      >
        Cierres de Caja
      </NavLink>
    </nav>
  );
}
