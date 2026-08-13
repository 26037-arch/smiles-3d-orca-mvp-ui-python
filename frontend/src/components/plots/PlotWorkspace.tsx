import { useEffect, useMemo, useState } from 'react'
import type { Data, Layout } from 'plotly.js'
import { ArrowLeft, BoxSelect, ChartNoAxesCombined, Layers3, LoaderCircle } from 'lucide-react'
import { api } from '../../api/client'
import { orbitalOptionLabel } from '../../chem/orbitals'
import { useAnalysisStore } from '../../store/analysisStore'
import { useProjectStore } from '../../store/projectStore'
import type { Orbital, PlotCut, PlotSample, PlotSampleRequest } from '../../types'
import { PlotlyFigure } from './PlotlyFigure'

const COLORS = ['#3d80ff', '#ff9f43', '#ffd43b', '#ff4f87', '#a66cff']
const DENSITY_COLOR = '#52c9a8'

function fieldRequest(orbital?: Orbital): PlotSampleRequest['field'] {
  return orbital ? {
    field: 'mo',
    orbital_internal_id: orbital.internal_id,
    orbital_index: orbital.orca_index,
    spin: orbital.spin,
  } : { field: 'total_density' }
}

export function PlotWorkspace() {
  const result = useProjectStore(state => state.result)
  const selection = useProjectStore(state => state.selection)
  const setError = useProjectStore(state => state.setError)
  const mode = useAnalysisStore(state => state.fieldMode)
  const cutKind = useAnalysisStore(state => state.cutKind)
  const selectedMoIds = useAnalysisStore(state => state.selectedMoIds)
  const planeOverlay = useAnalysisStore(state => state.planeOverlay)
  const setMode = useAnalysisStore(state => state.setMode)
  const setFieldMode = useAnalysisStore(state => state.setFieldMode)
  const setCutKind = useAnalysisStore(state => state.setCutKind)
  const setPlaneOverlay = useAnalysisStore(state => state.setPlaneOverlay)
  const toggleMo = useAnalysisStore(state => state.toggleMo)
  const [source, setSource] = useState<'axis' | 'atoms'>('axis')
  const [lineAxis, setLineAxis] = useState<'x' | 'y' | 'z'>('x')
  const [planeAxis, setPlaneAxis] = useState<'xy' | 'yz' | 'zx'>('xy')
  const [offset, setOffset] = useState(0)
  const [padding, setPadding] = useState(2)
  const [samples, setSamples] = useState<Record<string, PlotSample>>({})
  const [loading, setLoading] = useState(false)
  const [sampleError, setSampleError] = useState<string>()
  const orbitals = useMemo(() => result?.orbitals ?? [], [result?.orbitals])
  const selectedOrbitals = useMemo(
    () => orbitals.filter(orbital => selectedMoIds.includes(orbital.internal_id)),
    [orbitals, selectedMoIds],
  )

  useEffect(() => {
    if (!selectedMoIds.length && result?.homo_internal_id) toggleMo(result.homo_internal_id)
  }, [result?.homo_internal_id, selectedMoIds.length, toggleMo])

  const cut = useMemo<PlotCut | undefined>(() => {
    if (cutKind === 'line') {
      if (source === 'axis') return { kind: 'axis_line', axis: lineAxis, offsets: [offset, 0] }
      return selection.length >= 2
        ? { kind: 'atom_line', atom_ids: selection.slice(0, 2) as [string, string] }
        : undefined
    }
    if (source === 'axis') return { kind: 'axis_plane', plane: planeAxis, offset }
    return selection.length >= 3
      ? { kind: 'atom_plane', atom_ids: selection.slice(0, 3) as [string, string, string] }
      : undefined
  }, [cutKind, lineAxis, offset, planeAxis, selection, source])

  useEffect(() => {
    if (!result || !cut || result.demo) return
    const fields = mode === 'mo' ? selectedOrbitals : [undefined]
    if (!fields.length) { setSamples({}); return }
    let cancelled = false
    setLoading(true)
    setSampleError(undefined)
    void Promise.all(fields.map(async orbital => {
      const field = fieldRequest(orbital)
      const sample = await api.samplePlot(result.job_id, {
        field,
        cut,
        bounds: { automatic: true, padding },
        line_samples: 512,
        plane_samples_u: 80,
        plane_samples_v: 80,
        cube_resolution: 40,
      })
      return [orbital?.internal_id ?? 'density', sample] as const
    })).then(entries => {
      if (!cancelled) setSamples(Object.fromEntries(entries))
    }).catch(error => {
      if (!cancelled) setSampleError((error as Error).message)
    }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [cut, mode, padding, result, selectedOrbitals])

  if (!result || result.demo) return <div className="plot-workspace plot-unavailable"><button onClick={() => setMode('model')}><ArrowLeft /> 분자 화면</button><p>실제 ORCA 계산 결과가 있어야 파동함수 그래프를 만들 수 있습니다.</p></div>

  const displayed = mode === 'mo'
    ? selectedOrbitals.map((orbital, index) => ({ orbital, sample: samples[orbital.internal_id], color: COLORS[index] }))
    : [{ orbital: undefined, sample: samples.density, color: DENSITY_COLOR }]
  const ready = displayed.filter(item => item.sample)
  const lineData: Data[] = ready.filter(item => item.sample.kind === 'line').map(item => ({
    type: 'scatter', mode: 'lines',
    x: item.sample.kind === 'line' ? item.sample.coordinates : [],
    y: item.sample.kind === 'line' ? item.sample.values : [],
    name: item.orbital ? orbitalOptionLabel(item.orbital) : '전체 전자 밀도',
    line: { color: item.color, width: 2 }, connectgaps: false,
    hovertemplate: `%{x:.3f} Å<br>${item.orbital ? 'ψ' : 'ρ'}=%{y:.6g}<extra>%{fullData.name}</extra>`,
  }))
  const planeReady = ready.filter(item => item.sample.kind === 'plane')
  const combinePlanes = mode === 'mo' && planeOverlay
  const planeData = planeReady.map((item, index) => ({
    type: 'surface', scene: combinePlanes ? 'scene' : index === 0 ? 'scene' : `scene${index + 1}`,
    x: item.sample.kind === 'plane' ? item.sample.u : [],
    y: item.sample.kind === 'plane' ? item.sample.v : [],
    z: item.sample.kind === 'plane' ? item.sample.values : [],
    name: item.orbital ? orbitalOptionLabel(item.orbital) : '전체 전자 밀도',
    colorscale: [[0, item.color], [1, item.color]], showscale: false,
    opacity: combinePlanes ? 0.45 : 1,
    showlegend: combinePlanes,
    hovertemplate: `u=%{x:.3f} Å<br>v=%{y:.3f} Å<br>${item.orbital ? 'ψ' : 'ρ'}=%{z:.6g}<extra>%{fullData.name}</extra>`,
  })) as Data[]
  const planeLayout: Partial<Layout> = {
    title: { text: mode === 'mo' ? `MO ψ 평면 그래프${combinePlanes ? ' · 겹쳐 보기' : ''}` : '전체 전자 밀도 ρ 평면 그래프' },
    showlegend: combinePlanes,
  }
  planeReady.forEach((_, index) => {
    if (combinePlanes && index > 0) return
    const count = combinePlanes ? 1 : planeReady.length
    const columns = Math.min(3, count)
    const rows = Math.ceil(count / columns)
    const column = index % columns
    const row = Math.floor(index / columns)
    const sceneName = combinePlanes || index === 0 ? 'scene' : `scene${index + 1}`
    Object.assign(planeLayout, { [sceneName]: {
      domain: { x: [column / columns, (column + 1) / columns], y: [1 - (row + 1) / rows, 1 - row / rows] },
      xaxis: { title: { text: 'u (Å)' }, showgrid: true }, yaxis: { title: { text: 'v (Å)' }, showgrid: true },
      zaxis: { title: { text: mode === 'mo' ? 'ψ (a.u.)' : 'ρ (a.u.)' } },
      bgcolor: '#081421',
    } })
  })

  return <section className="plot-workspace">
    <div className="plot-field-toggle" aria-label="그래프 종류">
      <button className={mode === 'mo' ? 'active' : ''} onClick={() => setFieldMode('mo')}>MO</button>
      <button className={mode === 'total_density' ? 'active density' : ''} onClick={() => setFieldMode('total_density')}>전체 전자 밀도</button>
    </div>
    <aside className="plot-controls">
      <button className="back-model" onClick={() => setMode('model')}><ArrowLeft /> 분자 화면</button>
      <div className="plot-kind"><button className={cutKind === 'line' ? 'active' : ''} onClick={() => setCutKind('line')}><ChartNoAxesCombined /> 직선</button><button className={cutKind === 'plane' ? 'active' : ''} onClick={() => setCutKind('plane')}><BoxSelect /> 평면</button></div>
      {mode === 'mo' && cutKind === 'plane' && <button className={`plot-overlay-toggle ${planeOverlay ? 'active' : ''}`} disabled={selectedOrbitals.length < 2} onClick={() => setPlaneOverlay(!planeOverlay)}><Layers3 /> {planeOverlay ? 'MO 개별 그래프로 보기' : '모든 MO 겹쳐 보기'}</button>}
      <label>기준<select value={source} onChange={event => setSource(event.target.value as 'axis' | 'atoms')}><option value="axis">전역 좌표계</option><option value="atoms">선택 원자</option></select></label>
      {source === 'axis' && cutKind === 'line' && <label>축<select value={lineAxis} onChange={event => setLineAxis(event.target.value as 'x' | 'y' | 'z')}><option>x</option><option>y</option><option>z</option></select></label>}
      {source === 'axis' && cutKind === 'plane' && <label>평면<select value={planeAxis} onChange={event => setPlaneAxis(event.target.value as 'xy' | 'yz' | 'zx')}><option>xy</option><option>yz</option><option>zx</option></select></label>}
      {source === 'axis' && <label>Offset (Å)<input type="number" step="0.1" value={offset} onChange={event => setOffset(Number(event.target.value))} /></label>}
      {source === 'atoms' && <p className="plot-note">분자 화면에서 {cutKind === 'line' ? '원자 2개' : '원자 3개'}를 순서대로 선택하세요. 현재 {selection.length}개 선택됨.</p>}
      <label>자동 범위 여백 (Å)<input type="number" min="0" max="20" step="0.5" value={padding} onChange={event => setPadding(Number(event.target.value))} /></label>
      {mode === 'mo' && <div className="plot-orbitals"><strong>MO 그래프 ({selectedMoIds.length}/5)</strong><select value="" onChange={event => { if (event.target.value && !toggleMo(event.target.value)) setError('MO 그래프는 최대 5개입니다') }}><option value="">MO 추가</option>{orbitals.filter(item => !selectedMoIds.includes(item.internal_id)).map(item => <option key={item.internal_id} value={item.internal_id}>{orbitalOptionLabel(item)}</option>)}</select>{selectedOrbitals.map((item, index) => <button key={item.internal_id} style={{ borderColor: COLORS[index] }} onClick={() => toggleMo(item.internal_id)}>{orbitalOptionLabel(item)} ×</button>)}</div>}
      {mode === 'total_density' && <p className="density-note">전자밀도 전용 그래프입니다. MO의 ψ 축과 혼합하지 않습니다.</p>}
    </aside>
    <div className="plot-canvas">
      {loading && <div className="plot-loading"><LoaderCircle className="spin" /> Cube 샘플링 중</div>}
      {sampleError && <div className="plot-error">{sampleError}</div>}
      {!cut && <div className="plot-empty">필요한 원자를 먼저 선택하세요.</div>}
      {cut && !loading && !sampleError && !ready.length && <div className="plot-empty">표시할 {mode === 'mo' ? 'MO를 선택' : '전자밀도 데이터를 준비'}하세요.</div>}
      {ready.length > 0 && cutKind === 'line' && <PlotlyFigure data={lineData} layout={{ title: { text: mode === 'mo' ? 'MO ψ 직선 그래프' : '전체 전자 밀도 ρ 직선 그래프' }, hovermode: 'x unified', xaxis: { title: { text: '위치 (Å)' }, showgrid: false, showspikes: true, spikemode: 'across' }, yaxis: { title: { text: mode === 'mo' ? 'ψ (a.u.)' : 'ρ (a.u.)' }, showgrid: false } }} />}
      {ready.length > 0 && cutKind === 'plane' && <PlotlyFigure data={planeData} layout={planeLayout} />}
    </div>
  </section>
}
