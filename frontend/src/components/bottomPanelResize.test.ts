import { describe, expect, it } from 'vitest'
import {
  clampBottomPanelHeight,
  DEFAULT_BOTTOM_PANEL_HEIGHT,
  MIN_BOTTOM_PANEL_HEIGHT,
} from './bottomPanelResize'

describe('bottom panel resizing', () => {
  it('keeps the default height inside a normal desktop viewport', () => {
    expect(clampBottomPanelHeight(DEFAULT_BOTTOM_PANEL_HEIGHT, 900)).toBe(246)
  })

  it('enforces the minimum panel height', () => {
    expect(clampBottomPanelHeight(40, 900)).toBe(MIN_BOTTOM_PANEL_HEIGHT)
  })

  it('keeps enough vertical space for the molecular viewport', () => {
    expect(clampBottomPanelHeight(900, 700)).toBe(482)
  })
})
