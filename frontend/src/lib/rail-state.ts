export type ProjectRailState = "closed" | "project_operations" | "explicit";

export function resolveProjectRailState({
  selectedCount,
  dismissed,
  explicitContext,
}: {
  selectedCount: number;
  dismissed: boolean;
  explicitContext: boolean;
}): ProjectRailState {
  if (explicitContext) return "explicit";
  if (!selectedCount || dismissed) return "closed";
  return "project_operations";
}
