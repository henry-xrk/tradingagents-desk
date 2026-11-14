const EMPTY = "-";

export interface HistoryCursorState {
  cursor: string;
  stack: string;
}

export function pushHistoryCursor(stack: string, currentCursor: string, nextCursor: string): HistoryCursorState {
  const parts = stack ? stack.split("~") : [];
  parts.push(currentCursor || EMPTY);
  return { cursor: nextCursor, stack: parts.join("~") };
}

export function popHistoryCursor(stack: string): HistoryCursorState | null {
  const parts = stack ? stack.split("~") : [];
  const previous = parts.pop();
  if (previous === undefined) return null;
  return { cursor: previous === EMPTY ? "" : previous, stack: parts.join("~") };
}
