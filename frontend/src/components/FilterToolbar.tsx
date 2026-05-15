import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { InvoiceListParams } from "../types/invoice";

interface FilterToolbarProps {
  onFilter: (params: InvoiceListParams) => void;
}

export default function FilterToolbar({ onFilter }: FilterToolbarProps) {
  const [status, setStatus] = useState("all");
  const [proveedor, setProveedor] = useState("");
  const [fechaFrom, setFechaFrom] = useState("");
  const [fechaTo, setFechaTo] = useState("");
  const [q, setQ] = useState("");

  function handleFilter() {
    onFilter({
      status: status === "all" ? undefined : status || undefined,
      proveedor: proveedor || undefined,
      fecha_from: fechaFrom || undefined,
      fecha_to: fechaTo || undefined,
      q: q || undefined,
    });
  }

  function handleClear() {
    setStatus("all");
    setProveedor("");
    setFechaFrom("");
    setFechaTo("");
    setQ("");
    onFilter({});
  }

  return (
    <div className="flex flex-col md:flex-row md:flex-wrap md:items-end gap-2 p-4 bg-gray-50 border-b border-gray-200">
      <Select value={status} onValueChange={setStatus}>
        <SelectTrigger className="min-h-[44px] w-full md:w-auto">
          <SelectValue placeholder="Todos los estados" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Todos los estados</SelectItem>
          <SelectItem value="auto_saved">Guardado</SelectItem>
          <SelectItem value="pending_review">Revisar</SelectItem>
          <SelectItem value="confirmed">Confirmado</SelectItem>
          <SelectItem value="rejected">Rechazado</SelectItem>
        </SelectContent>
      </Select>

      <Input
        value={proveedor}
        onChange={(e) => setProveedor(e.target.value)}
        placeholder="Proveedor"
        className="min-h-[44px] w-full md:w-auto"
      />

      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-500 font-medium">Desde</label>
        <Input
          type="date"
          value={fechaFrom}
          onChange={(e) => setFechaFrom(e.target.value)}
          className="min-h-[44px] w-full md:w-auto"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-gray-500 font-medium">Hasta</label>
        <Input
          type="date"
          value={fechaTo}
          onChange={(e) => setFechaTo(e.target.value)}
          className="min-h-[44px] w-full md:w-auto"
        />
      </div>

      <Input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Buscar…"
        className="min-h-[44px] w-full md:w-auto"
      />

      <Button
        onClick={handleFilter}
        className="w-full md:w-auto min-h-[44px]"
      >
        Filtrar
      </Button>

      <span
        onClick={handleClear}
        className="text-sm text-blue-600 cursor-pointer self-end pb-[10px]"
      >
        Limpiar filtros
      </span>
    </div>
  );
}
