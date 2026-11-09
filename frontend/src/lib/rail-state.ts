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

/**
 * A dashboard reload can overlap with an earlier filter reload.  Only the
 * response that belongs to the newest request is allowed to update the table.
 */
export function shouldApplyDashboardLoad(requestSequence: number, latestSequence: number) {
  return requestSequence === latestSequence;
}

export function shouldClearProjectSelection(previousResultSet: string, nextResultSet: string) {
  return previousResultSet !== nextResultSet;
}
