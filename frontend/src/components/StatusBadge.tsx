import { Badge } from "@/components/ui/badge";

const MAP: Record<string, "success" | "warning" | "destructive" | "secondary" | "default"> = {
  READY: "success", PUBLISHED: "success", SCHEDULED: "success", SUCCEEDED: "success", UPLOADED_PRIVATE: "success",
  FAILED: "destructive", CANCELLED: "secondary", DRY_RUN: "secondary", QUEUED: "warning", PENDING: "secondary",
};

export function StatusBadge({ status }: { status: string }) {
  const variant = MAP[status] ?? "default";
  const label = status === "UPLOADED_PRIVATE" ? "Uploaded (private)" : status === "DRY_RUN" ? "Dry run" : status.replace(/_/g, " ").toLowerCase();
  return <Badge variant={variant} className="capitalize">{label}</Badge>;
}
