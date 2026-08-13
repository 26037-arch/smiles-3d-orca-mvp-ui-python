import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, ChevronDown, RotateCcw, TerminalSquare, ZoomIn, ZoomOut } from 'lucide-react'
import { useAnalysisStore } from '../store/analysisStore'
import { useProjectStore } from '../store/projectStore'
import {
  DEFAULT_ENERGY_BREAK_THRESHOLD_EV,
  energyAtPosition,
  layoutEnergyLevels,
  positionForEnergy,
} from './energyDiagramLayout'
import { clampBottomPanelHeight, MIN_BOTTOM_PANEL_HEIGHT } from './bottomPanelResize'

const MIN_ZOOM = 1
const MAX_ZOOM = 8
const ZOOM_STEP = 1.25
const HARTREE_TO_EV = 27.211386245988

export function BottomPanel({
  log,
  height,
  onHeightChange,
}: {
  job?: unknown
  log: string
  height: number
  onHeightChange(height: number): void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [tab, setTab] = useState<'orbitals' | 'log'>('orbitals')
  const [unit, setUnit] = useState<'eV' | 'Eh'>('eV')
  const [zoom, setZoom] = useState(1)
  const [breakThresholdEv, setBreakThresholdEv] = useState(DEFAULT_ENERGY_BREAK_THRESHOLD_EV)
  const [expandedBreakKeys, setExpandedBreakKeys] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const result = useProjectStore(state => state.result)
  const calculationKind = useProjectStore(state => state.calculationKind)
  const reactionPath = useProjectStore(state => state.reactionPath)
  const reactionFrameIndex = useProjectStore(state => state.reactionFrameIndex)
  const reactionFrame = reactionPath?.displayFrames[reactionFrameIndex]
  const reactionImage = reactionFrame?.isCalculated
    ? reactionPath?.path.images[reactionFrame.leftImageIndex]
    : undefined
  const selected = useProjectStore(state => state.selectedOrbital)
  const setSelected = useProjectStore(state => state.setSelectedOrbital)
  const setError = useProjectStore(state => state.setError)
  const analysisMode = useAnalysisStore(state => state.mode)
  const graphMoIds = useAnalysisStore(state => state.selectedMoIds)
  const addGraphMo = useAnalysisStore(state => state.addMo)
  const setGraphFieldMode = useAnalysisStore(state => state.setFieldMode)
  const orbitals = useMemo(
    () => calculationKind === 'reaction-path' ? reactionImage?.orbitals ?? [] : result?.orbitals ?? [],
    [calculationKind, reactionImage?.orbitals, result?.orbitals],
  )
  const expandedBreakKeySet = useMemo(() => new Set(expandedBreakKeys), [expandedBreakKeys])
  const layout = useMemo(() => layoutEnergyLevels(orbitals, zoom, {
    breakThresholdEv,
    expandedBreakKeys: expandedBreakKeySet,
  }), [breakThresholdEv, expandedBreakKeySet, orbitals, zoom])
  const factor = unit === 'eV' ? HARTREE_TO_EV : 1

  useEffect(() => {
    setZoom(1)
    setExpandedBreakKeys([])
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [result?.job_id, reactionImage?.index])

  useEffect(() => {
    const fitToViewport = () => onHeightChange(clampBottomPanelHeight(height, window.innerHeight))
    window.addEventListener('resize', fitToViewport)
    return () => window.removeEventListener('resize', fitToViewport)
  }, [height, onHeightChange])

  const beginResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startY = event.clientY
    const startHeight = height
    const handleMove = (moveEvent: PointerEvent) => {
      onHeightChange(clampBottomPanelHeight(
        startHeight + startY - moveEvent.clientY,
        window.innerHeight,
      ))
    }
    const stop = () => {
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      document.body.classList.remove('resizing-bottom-panel')
    }
    document.body.classList.add('resizing-bottom-panel')
    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
  }

  const zoomAt = (requestedZoom: number) => {
    const nextZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, requestedZoom))
    if (nextZoom === zoom) return
    const scroll = scrollRef.current
    if (!scroll) return setZoom(nextZoom)
    const anchorY = scroll.clientHeight / 2
    const anchorEnergy = energyAtPosition(layout, scroll.scrollTop + anchorY)
    const nextLayout = layoutEnergyLevels(orbitals, nextZoom, {
      breakThresholdEv,
      expandedBreakKeys: expandedBreakKeySet,
    })
    setZoom(nextZoom)
    window.requestAnimationFrame(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = Math.max(
          0,
          positionForEnergy(nextLayout, anchorEnergy) - anchorY,
        )
      }
    })
  }

  const setBreakExpanded = (key: string, expanded: boolean) => {
    setExpandedBreakKeys(keys => expanded
      ? [...new Set([...keys, key])]
      : keys.filter(existing => existing !== key))
  }

  const selectEnergyOrbital = (orbitalId: string) => {
    setSelected(orbitalId)
    if (analysisMode !== 'plot') return
    setGraphFieldMode('mo')
    if (!addGraphMo(orbitalId)) setError('MO 그래프는 최대 5개입니다')
  }

  return (
    <section className={`bottom-panel ${collapsed ? 'collapsed' : ''}`}>
      {!collapsed && <div
        className="bottom-resize-handle"
        role="separator"
        aria-label="에너지 도표와 계산 로그 높이 조절"
        aria-orientation="horizontal"
        aria-valuemin={MIN_BOTTOM_PANEL_HEIGHT}
        aria-valuenow={height}
        tabIndex={0}
        onPointerDown={beginResize}
        onKeyDown={event => {
          if (event.key === 'ArrowUp') onHeightChange(clampBottomPanelHeight(height + 20, window.innerHeight))
          if (event.key === 'ArrowDown') onHeightChange(clampBottomPanelHeight(height - 20, window.innerHeight))
          if (event.key === 'Home') onHeightChange(MIN_BOTTOM_PANEL_HEIGHT)
          if (['ArrowUp', 'ArrowDown', 'Home'].includes(event.key)) event.preventDefault()
        }}
      ><span /></div>}
      <header>
        <div className="bottom-tabs">
          <button className={tab === 'orbitals' ? 'active' : ''} onClick={() => setTab('orbitals')}>
            <Activity /> MO 에너지
          </button>
          <button className={tab === 'log' ? 'active' : ''} onClick={() => setTab('log')}>
            <TerminalSquare /> 계산 로그
          </button>
        </div>
        <div className="result-summary">
          {result ? <>
            <span><small>최종 총에너지</small><b>{result.total_energy_hartree.toFixed(8)} Eh</b></span>
            <span><small>수렴</small><b className="converged">SCF · Geometry</b></span>
            <span className="local-label">{result.local_minimum_notice}</span>
            {result.demo && <em>DEMO · 실제 계산 아님</em>}
          </> : reactionImage ? <>
            <span><small>ORCA geometry</small><b>{reactionImage.index + 1}/{reactionPath?.path.images.length}</b></span>
            <span><small>Geometry energy</small><b>{reactionImage.energyHartree?.toFixed(8) ?? '없음'} Eh</b></span>
            <span className="local-label">SCF iteration별 MO가 아닌 geometry 수렴 wavefunction</span>
          </> : <span>{calculationKind === 'reaction-path' ? '보간 표시 · 전자구조 값 없음' : '계산 결과 없음'}</span>}
          <button className="icon-button" onClick={() => setCollapsed(!collapsed)}><ChevronDown /></button>
        </div>
      </header>
      {!collapsed && <div className="bottom-content">
        {tab === 'log' ? <pre className="job-log">{log || '로그가 없습니다.'}</pre> : orbitals.length ? (
          <div className="energy-diagram">
            <div
              ref={scrollRef}
              className="energy-scroll"
              aria-label="MO 에너지 준위 목록"
            >
              <div className="energy-chart" style={{ height: layout.height }}>
                <div className="energy-axis">
                  <b>{unit}</b>
                  {layout.ticks.map(tick => <div
                    key={tick.energyHartree}
                    className="energy-tick"
                    style={{ top: tick.top }}
                  ><span>{(tick.energyHartree * factor).toFixed(unit === 'eV' ? 1 : 2)}</span></div>)}
                  {layout.breaks.map(gap => <div
                    key={gap.key}
                    className="axis-break"
                    style={{ top: gap.top }}
                    title={`${gap.gapEv.toFixed(2)} eV 구간 생략`}
                  >≈</div>)}
                  {layout.expandedRanges.map(range => <button
                    key={`bracket:${range.key}`}
                    className="axis-bracket"
                    style={{ top: range.top, height: range.bottom - range.top }}
                    onClick={() => setBreakExpanded(range.key, false)}
                    title={`${range.gapEv.toFixed(2)} eV 구간을 다시 물결로 접기`}
                    aria-label={`${range.gapEv.toFixed(2)} eV 구간 접기`}
                  ><span>{range.gapEv.toFixed(1)} eV</span></button>)}
                </div>
                <div className="levels">
                  {layout.ticks.map(tick => <div
                    key={`grid:${tick.energyHartree}`}
                    className="energy-gridline"
                    style={{ top: tick.top }}
                  />)}
                  {layout.breaks.map(gap => <button
                    key={`break:${gap.key}`}
                    className="level-break"
                    style={{ top: gap.top }}
                    onClick={() => setBreakExpanded(gap.key, true)}
                    title={`${gap.gapEv.toFixed(2)} eV 생략 구간 펼치기`}
                    aria-label={`${gap.gapEv.toFixed(2)} eV 생략 구간 펼치기`}
                  ><span>∿∿∿∿∿∿∿∿∿∿∿∿</span><small>{gap.gapEv.toFixed(1)} eV 생략</small></button>)}
                  {layout.levels.map(({ orbital, top, lane, laneCount }) => {
                    const gap = 2
                    const usableWidth = 86
                    const width = (usableWidth - gap * (laneCount - 1)) / laneCount
                    const left = 7 + lane * (width + gap)
                    return (
                      <button
                        key={orbital.internal_id}
                        className={`level ${orbital.occupancy ? 'occupied' : 'virtual'} ${selected === orbital.internal_id ? 'selected' : ''} ${analysisMode === 'plot' && graphMoIds.includes(orbital.internal_id) ? 'graph-selected' : ''}`}
                        style={{ top, left: `${left}%`, width: `${width}%` }}
                        onClick={() => selectEnergyOrbital(orbital.internal_id)}
                        title={`ORCA index ${orbital.orca_index}; 표시 번호 ${orbital.display_number}`}
                      >
                        <i />
                        <span>{orbital.label ?? `MO ${orbital.display_number}`}</span>
                        <small>{(orbital.energy_hartree * factor).toFixed(3)}</small>
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
            <div className="diagram-legend">
              <span><i className="occ" /> 점유</span>
              <span><i className="virt" /> 비점유</span>
              <label className="break-threshold"><i className="break-mark">≈</i><span>물결 기준</span><input type="number" min="0.1" step="0.5" value={breakThresholdEv} onChange={event => { setBreakThresholdEv(Math.max(0.1, Number(event.target.value))); setExpandedBreakKeys([]) }} /><b>eV</b></label>
              <div className="zoom-controls">
                <button aria-label="축소" disabled={zoom <= MIN_ZOOM} onClick={() => zoomAt(zoom / ZOOM_STEP)}><ZoomOut /></button>
                <b>{zoom.toFixed(2)}×</b>
                <button aria-label="확대" disabled={zoom >= MAX_ZOOM} onClick={() => zoomAt(zoom * ZOOM_STEP)}><ZoomIn /></button>
                <button aria-label="확대 초기화" disabled={zoom === 1} onClick={() => zoomAt(1)}><RotateCcw /></button>
              </div>
              <small className="zoom-hint">버튼: 도표 중앙 기준 확대<br />물결 클릭: 생략 구간 펼치기</small>
              <button className="unit-toggle" onClick={() => setUnit(unit === 'eV' ? 'Eh' : 'eV')}>
                {unit} → {unit === 'eV' ? 'Eh' : 'eV'}
              </button>
            </div>
          </div>
        ) : <div className="empty-diagram">오비탈 데이터가 없습니다. 계산이 전자구조 출력을 만들지 못했거나 아직 실행되지 않았습니다.</div>}
      </div>}
    </section>
  )
}
