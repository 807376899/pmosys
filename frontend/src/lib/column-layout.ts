export function applySharedOrder<T extends string>(sharedOrder: readonly T[], visibleColumns: readonly T[]) {
  const visible = new Set(visibleColumns);
  return sharedOrder.filter((column) => visible.has(column));
}

export function insertStageGroup<T extends string>(columns: readonly T[], anchor: T | null) {
  if (!anchor || !columns.includes(anchor)) return ["stage_group" as const, ...columns];
  const index = columns.indexOf(anchor);
  return [...columns.slice(0, index + 1), "stage_group" as const, ...columns.slice(index + 1)];
}

export function stageLayoutForVisibleColumns<T extends string>(
  configuredColumns: readonly T[],
  visibleColumns: readonly T[],
  anchor: T | null,
) {
  const visible = new Set(visibleColumns);
  return insertStageGroup(configuredColumns, anchor).filter((column) => column === "stage_group" || visible.has(column));
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

export type TableColumnWidths = Record<"overview" | "stage" | "annual", Record<string, number>>;

export function readTableColumnWidths(value: unknown): TableColumnWidths {
  const source = value && typeof value === "object" ? value as Partial<TableColumnWidths> : {};
  const sanitize = (widths: unknown) => Object.fromEntries(
    Object.entries(widths && typeof widths === "object" ? widths : {})
      .filter(([, width]) => typeof width === "number" && Number.isFinite(width) && width > 0),
  );
  return {
    overview: sanitize(source.overview),
    stage: sanitize(source.stage),
    annual: sanitize(source.annual),
  };
}

export function clampColumnWidth(width: number, minimum: number) {
  return Math.max(minimum, Math.round(width));
}

export function setViewColumnWidth(
  widths: TableColumnWidths,
  view: keyof TableColumnWidths,
  key: string,
  width: number,
  minimum: number,
): TableColumnWidths {
  return { ...widths, [view]: { ...widths[view], [key]: clampColumnWidth(width, minimum) } };
}

export function resetViewColumnWidths(widths: TableColumnWidths, view: keyof TableColumnWidths): TableColumnWidths {
  return { ...widths, [view]: {} };
}
