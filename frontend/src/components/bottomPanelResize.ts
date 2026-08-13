export const DEFAULT_BOTTOM_PANEL_HEIGHT = 246
export const MIN_BOTTOM_PANEL_HEIGHT = 140
const TOP_BAR_HEIGHT = 58
const MIN_VIEWPORT_HEIGHT = 160

export function clampBottomPanelHeight(height: number, viewportHeight: number) {
  const maximum = Math.max(
    MIN_BOTTOM_PANEL_HEIGHT,
    viewportHeight - TOP_BAR_HEIGHT - MIN_VIEWPORT_HEIGHT,
  )
  return Math.round(Math.min(maximum, Math.max(MIN_BOTTOM_PANEL_HEIGHT, height)))
}
