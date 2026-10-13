export function applySharedOrder<T extends string>(sharedOrder: readonly T[], visibleColumns: readonly T[]) {
  const visible = new Set(visibleColumns);
  return sharedOrder.filter((column) => visible.has(column));
}

export function insertStageGroup<T extends string>(columns: readonly T[], anchor: T | null) {
  if (!anchor || !columns.includes(anchor)) return ["stage_group" as const, ...columns];
  const index = columns.indexOf(anchor);
  return [...columns.slice(0, index + 1), "stage_group" as const, ...columns.slice(index + 1)];
}

export function replaceVisibleOrder<T extends string>(sharedOrder: readonly T[], visibleColumns: readonly T[], reorderedVisibleColumns: readonly T[]) {
  const visible = new Set(visibleColumns);
  const reordered = [...reorderedVisibleColumns];
  return sharedOrder.map((column) => visible.has(column) ? reordered.shift() ?? column : column);
}

export function stageGroupAnchorForLayout<T extends string>(layout: readonly (T | "stage_group")[]) {
  const index = layout.indexOf("stage_group");
  return index > 0 ? layout[index - 1] as T : null;
}
