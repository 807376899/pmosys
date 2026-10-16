export type ProjectRailState = "closed" | "project_operations" | "explicit";
export type WorkbenchView = "overview" | "stage" | "annual";

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

export function resolveWorkbenchRailVisibility(
  view: WorkbenchView,
  projectRailState: ProjectRailState,
) {
  return view === "annual" || projectRailState !== "closed";
}
