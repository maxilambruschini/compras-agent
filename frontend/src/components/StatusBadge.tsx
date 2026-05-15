import { Badge } from "@/components/ui/badge";

interface StatusBadgeProps {
  status: string;
}

const STATUS_MAP: Record<string, { label: string; variant: "secondary" | "outline" | "default" | "destructive"; className?: string }> = {
  auto_saved: {
    label: "Guardado",
    variant: "secondary",
  },
  pending_review: {
    label: "Revisar",
    variant: "outline",
    className: "border-amber-500 text-amber-700 bg-amber-50",
  },
  confirmed: {
    label: "Confirmado",
    variant: "default",
    className: "bg-green-600 text-white",
  },
  rejected: {
    label: "Rechazado",
    variant: "destructive",
  },
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = STATUS_MAP[status] ?? { label: status, variant: "secondary" as const };
  return (
    <Badge
      variant={config.variant}
      className={config.className}
      aria-label={config.label}
    >
      {config.label}
    </Badge>
  );
}
