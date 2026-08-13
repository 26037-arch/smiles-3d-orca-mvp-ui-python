import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, Atom as AtomIcon, CheckCircle2, ChevronDown, CircleAlert, Eye, EyeOff, FlaskConical, Layers3, Plus, RefreshCcw, Settings2, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { ELEMENTS, normalizeElement } from '../chem/elements'
import { createSurfaceLayer, frontierOrbitals, orbitalOptionLabel, selectedOrbitalIdForBrowser, surfaceRequestForLayer, toggleSurfaceLayer } from '../chem/orbitals'
import { AO_PAGE_SIZE, appendCompositionItems, createBasisSurfaceLayer, deselectIncomingBasis, initialBasisSelection, isCurrentAORequest } from '../chem/aoComposition'
import { useProjectStore, visibleProject } from '../store/projectStore'
import type { BasisContribution, Capabilities, Orbital, OrbitalComposition, SurfaceLayer, Vec3 } from '../types'

function Section({ title, icon: Icon, children, open = true }: { title: string; icon: typeof Activity; children: React.ReactNode; open?: boolean }) {
  return <details className="panel-section" open={open}><summary><Icon /><span>{title}</span><ChevronDown className="chevron" /></summary><div className="section-content">{children}</div></details>
}

function CoordinateInput() {
  const addElement = useProjectStore(s => s.addElement); const setElement = useProjectStore(s => s.setAddElement); const addAtom = useProjectStore(s => s.addAtom); const setError = useProjectStore(s => s.setError)
  const [coords, setCoords] = useState<[string, string, string]>(['0', '0', '0'])
  const submit = () => { const element = normalizeElement(addElement); const position = coords.map(Number) as Vec3; if (!element) return setError('알 수 없는 원소 기호입니다'); if (position.some(x => !Number.isFinite(x))) return setError('x, y, z는 유한한 숫자여야 합니다'); addAtom(element, position) }
  return <div className="coordinate-add"><div className="field-row"><label>원소<input value={addElement} onChange={e => setElement(e.target.value)} list="elements" /></label><datalist id="elements">{Object.keys(ELEMENTS).map(e => <option key={e}>{e}</option>)}</datalist>{['x', 'y', 'z'].map((axis, i) => <label key={axis}>{axis} (Å)<input type="number" step="0.1" value={coords[i]} onChange={e => setCoords(coords.map((x, j) => j === i ? e.target.value : x) as [string, string, string])} /></label>)}</div><button className="wide primary" onClick={submit}><Plus /> 정확한 좌표로 원자 생성</button><p className="help">활성 스케치 평면을 클릭해도 같은 원소가 연속 배치됩니다. Esc로 취소합니다.</p></div>
}

function SelectedAtomPanel() {
  const selection = useProjectStore(s => s.selection); const project = useProjectStore(visibleProject); const update = useProjectStore(s => s.updateVisibleAtom); const remove = useProjectStore(s => s.deleteSelected)
  const atom = selection.length === 1 ? project.atoms.find(a => a.id === selection[0]) : undefined
  if (!atom) return <p className="empty-state">{selection.length ? `${selection.length}개 원자 선택됨` : '원자를 선택하면 정확한 좌표를 편집할 수 있습니다.'}</p>
  return <div><div className="atom-heading"><span className="element-dot" style={{ background: ELEMENTS[atom.element].color }}>{atom.element}</span><div><strong>{atom.element} 원자</strong><small>{atom.id}</small></div><button className="icon-button danger-ghost" onClick={remove}><Trash2 /></button></div><div className="field-row coords">{atom.position.map((value, i) => <label key={i}>{'xyz'[i]} (Å)<input type="number" step="0.01" value={value} onChange={e => { const position = [...atom.position] as Vec3; position[i] = Number(e.target.value); update(atom.id, { position }) }} /></label>)}</div><label>원소<select value={atom.element} onChange={e => update(atom.id, { element: e.target.value })}>{Object.keys(ELEMENTS).map(e => <option key={e}>{e}</option>)}</select></label></div>
}

function CalculationSettings({ capabilities }: { capabilities?: Capabilities }) {
  const project = useProjectStore(s => s.project); const update = useProjectStore(s => s.updateProject)
  const setNotice = useProjectStore(s => s.setNotice); const setError = useProjectStore(s => s.setError)
  const calculationKind = useProjectStore(s => s.calculationKind); const setCalculationKind = useProjectStore(s => s.setCalculationKind)
  const reactionStatus = useProjectStore(s => s.reactionStatus); const reactionError = useProjectStore(s => s.reactionError)
  const result = useProjectStore(s => s.result)
  const pathRequest = useRef<AbortController | undefined>(undefined)
  const [presets, setPresets] = useState<any[]>([]); useEffect(() => { api.presets().then(setPresets).catch(() => {}) }, [])
  const [orcaPath, setOrcaPath] = useState(capabilities?.orca.path ?? '')
  useEffect(() => setOrcaPath(capabilities?.orca.path ?? ''), [capabilities?.orca.path])
  const electrons = project.atoms.reduce((sum, atom) => sum + ELEMENTS[atom.element].atomicNumber, 0) - project.totalCharge
  const parityOk = electrons % 2 === (project.multiplicity - 1) % 2
  const savePath = async () => { try { await api.setOrcaPath(orcaPath.trim() || null); setNotice('ORCA 경로를 로컬 설정에 저장했습니다.'); window.setTimeout(() => window.location.reload(), 400) } catch (e) { setError((e as Error).message) } }
  useEffect(() => () => pathRequest.current?.abort(), [])
  const reactionJobId = project.lastCalculationId ?? result?.job_id
  const loadReactionPath = useCallback(async () => {
    const jobId = reactionJobId
    if (!jobId) return setError('최적화 경로를 읽을 계산 작업이 없습니다.')
    pathRequest.current?.abort()
    const controller = new AbortController(); pathRequest.current = controller
    useProjectStore.getState().beginReactionPathLoad()
    try {
      const playback = await api.reactionPath(jobId, controller.signal)
      if (pathRequest.current !== controller) return
      useProjectStore.getState().applyReactionPath(playback)
    } catch (error) {
      if (controller.signal.aborted) return
      useProjectStore.getState().failReactionPath((error as Error).message)
    }
  }, [reactionJobId, setError])
  return <div className="settings-grid">
    <label className="full">계산 종류<div className="calculation-kind" role="group" aria-label="계산 종류">
      <button className={calculationKind === 'single' ? 'active' : ''} onClick={() => { pathRequest.current?.abort(); setCalculationKind('single') }}>단일 구조</button>
      <button className={calculationKind === 'reaction-path' ? 'active' : ''} onClick={() => setCalculationKind('reaction-path')}>최적화 경로</button>
    </div></label>
    <label>전체 전하<input type="number" min="-20" max="20" value={project.totalCharge} onChange={e => update({ totalCharge: Number(e.target.value) })} /></label>
    <label>스핀 다중도<input type="number" min="1" max="20" value={project.multiplicity} onChange={e => update({ multiplicity: Number(e.target.value) })} /></label>
    <label className="full">계산 프리셋<select value={project.calculationPreset} onChange={e => update({ calculationPreset: e.target.value })}>{presets.map(p => <option key={p.id} value={p.id}>{p.name} · 비용 {p.cost}</option>)}</select></label>
    {calculationKind === 'reaction-path' && <div className="reaction-import full">
      <div className="endpoint-card"><strong>R0 입력 구조</strong><span>현재 편집 중인 구조 · {project.atoms.length}개 원자</span></div>
      <p className="help">R0에서 r2SCAN-3c 구조 최적화를 실행하고 ORCA가 실제로 계산한 geometry와 SCF 반복만 표시합니다. NEB·IRC·IDPP 계산이 아닙니다.</p>
      <p className="help">각 geometry는 선택한 프리셋으로 별도 single point를 수행하며, 처음에는 PAtom, 이후에는 직전 GBW를 읽습니다.</p>
      {reactionJobId && <button className="wide" disabled={reactionStatus === 'loading-path'} onClick={() => void loadReactionPath()}>{reactionStatus === 'loading-path' ? '경로 찾는 중…' : '현재 작업에서 최적화 경로 다시 불러오기'}</button>}
      <p className="help">계산 완료 후 schema 2 reaction-path.json을 자동 생성·로드합니다.</p>
      {reactionError && <p className="inline-error">{reactionError}</p>}
    </div>}
    <div className={`validation-line full ${parityOk ? 'ok' : 'bad'}`}>{parityOk ? <CheckCircle2 /> : <CircleAlert />}전자 수 {electrons} · {parityOk ? '다중도 parity 일치' : '전하·다중도 parity 불일치'}</div>
    {presets.filter(p => p.id === project.calculationPreset).map(p => <div key={p.id} className="preset-card full"><strong>{p.purpose}</strong><code>! {p.optimization_keywords.join(' ')}</code>{p.single_point_keywords.join(' ') !== p.optimization_keywords.join(' ') && <code>! {p.single_point_keywords.join(' ')}</code>}</div>)}
    <p className="help full">음이온·열린껍질·전이금속에서는 기본 프리셋이 부적절할 수 있습니다. 화학 상태를 앱이 추측하지 않습니다.</p>
    <label className="full">ORCA 실행 파일 경로<div className="path-field"><input value={orcaPath} placeholder="C:\\Program Files\\ORCA_6.1.1\\orca.exe" onChange={e => setOrcaPath(e.target.value)} /><button onClick={savePath}>저장</button></div></label>
    <div className="capability full"><span className={capabilities?.calculation.available ? 'dot good' : 'dot bad'} />{capabilities?.calculation.available ? `ORCA ${capabilities.orca.version} · OPI ${capabilities.opi.version}` : capabilities?.calculation.reasons.join(' · ') || '진단 중'}</div>
  </div>
}

function BondsAndPlanes() {
  const project = useProjectStore(s => s.project); const remove = useProjectStore(s => s.deleteBond); const order = useProjectStore(s => s.updateBondOrder); const reinfer = useProjectStore(s => s.reinferBonds); const active = useProjectStore(s => s.setActivePlane); const toggle = useProjectStore(s => s.togglePlane)
  const name = (id: string) => { const a = project.atoms.find(x => x.id === id); return a ? `${a.element}·${project.atoms.indexOf(a) + 1}` : '?' }
  return <><div className="list-heading"><span>결합 <b>{project.bonds.length}</b></span><button onClick={reinfer}><RefreshCcw /> 다시 추론</button></div><p className="help">거리·공유결합 반지름 기반의 표시용 추정입니다.</p><div className="compact-list">{project.bonds.map(b => <div key={b.id}><span className={`source ${b.source}`}>{b.source === 'manual' ? 'M' : 'I'}</span><span>{name(b.atomId1)}—{name(b.atomId2)}</span><select value={b.order} onChange={e => order(b.id, Number(e.target.value) as 1 | 2 | 3)}><option value="1">단일</option><option value="2">이중</option><option value="3">삼중</option></select><button className="icon-button" onClick={() => remove(b.id)}><Trash2 /></button></div>)}</div><div className="list-heading planes"><span>스케치 평면</span></div><div className="compact-list">{project.sketchPlanes.map(p => <div key={p.id} className={!p.valid ? 'invalid' : ''}><button className="icon-button" onClick={() => toggle(p.id)}>{p.visible ? <Eye /> : <EyeOff />}</button><span>{p.kind}{!p.valid && ' · 퇴화'}</span><button className={p.active ? 'tag active' : 'tag'} disabled={!p.valid} onClick={() => active(p.id)}>{p.active ? '활성' : '활성화'}</button></div>)}</div></>
}

function SurfaceControl({ layer }: { layer: SurfaceLayer }) {
  const result = useProjectStore(s => s.result); const upsert = useProjectStore(s => s.upsertSurface); const remove = useProjectStore(s => s.removeSurface)
  const [isovalue, setIso] = useState(layer.isovalue)
  useEffect(() => {
    if (!layer.visible) return
    if (layer.reactionFrame) {
      if (Math.abs(layer.isovalue - isovalue) > 1e-12) upsert({ ...layer, isovalue })
      return
    }
    if (!result) return
    const timer = window.setTimeout(async () => {
      const pending = { ...layer, isovalue, loading: true, error: undefined }; upsert(pending)
      try { const response = await api.surface(result.job_id, surfaceRequestForLayer(pending)); upsert({ ...pending, loading: false, meshUrls: response.mesh_urls, cacheHit: response.cache_hit }) }
      catch (e) { upsert({ ...pending, loading: false, error: (e as Error).message }) }
    }, 300)
    return () => window.clearTimeout(timer)
    // layer key identifies stable controls; opacity is renderer-only and intentionally excluded.
  // The layer object is replaced by upsert; primitive request inputs are the trigger.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isovalue, layer.visible, layer.reactionFrame, result?.job_id])
  return <div className="surface-card"><div><input type="checkbox" checked={layer.visible} onChange={e => upsert({ ...layer, visible: e.target.checked })} /><strong>{layer.name}</strong>{layer.loading && <span className="tiny-status">생성 중</span>}{layer.cacheHit && <span className="tiny-status cache">cache</span>}<button className="icon-button" onClick={() => remove(layer.key)}><Trash2 /></button></div><label>등밀도값 <input type="number" min="0.0001" step="0.005" value={isovalue} onChange={e => setIso(Math.max(.0001, Number(e.target.value)))} /></label><input aria-label="등밀도값 로그 슬라이더" type="range" min="-4" max="-0.3" step="0.02" value={Math.log10(isovalue)} onChange={e => setIso(10 ** Number(e.target.value))} /><label>투명도 <b>{layer.opacity.toFixed(2)}</b><input type="range" min="0" max="1" step="0.01" value={layer.opacity} onChange={e => upsert({ ...layer, opacity: Number(e.target.value) })} /></label>{layer.error && <p className="inline-error">{layer.error}</p>}</div>
}

function SurfacesPanel() {
  const result = useProjectStore(s => s.result); const layers = useProjectStore(s => s.surfaces); const upsert = useProjectStore(s => s.upsertSurface); const selected = useProjectStore(s => s.selectedOrbital); const setSelected = useProjectStore(s => s.setSelectedOrbital); const setError = useProjectStore(s => s.setError)
  const calculationKind = useProjectStore(s => s.calculationKind)
  const reactionPath = useProjectStore(s => s.reactionPath)
  const reactionFrameIndex = useProjectStore(s => s.reactionFrameIndex)
  const displayFrame = reactionPath?.displayFrames[reactionFrameIndex]
  const reactionImage = displayFrame ? reactionPath?.path.images[displayFrame.leftImageIndex] : undefined
  const reactionOrbitals = reactionImage?.orbitals
  const availableOrbitals = useMemo(
    () => calculationKind === 'reaction-path' ? reactionOrbitals ?? [] : result?.orbitals ?? [],
    [calculationKind, reactionOrbitals, result?.orbitals],
  )
  const reactionHasWavefunctions = Boolean(reactionPath?.path.images[0]?.wavefunctionRef)
  const [extraOrbitalId, setExtraOrbitalId] = useState('')
  const frontier = useMemo(() => frontierOrbitals(availableOrbitals, result?.homo_internal_id), [availableOrbitals, result?.homo_internal_id])
  const extraOrbital = availableOrbitals.find(orbital => orbital.internal_id === extraOrbitalId)
  useEffect(() => {
    setExtraOrbitalId(selectedOrbitalIdForBrowser(availableOrbitals, selected))
  }, [availableOrbitals, result?.job_id, selected])
  const addLayer = (orbital?: Orbital) => {
    if (orbital) setSelected(orbital.internal_id)
    if (calculationKind === 'reaction-path' && orbital) return
    if (!result) return setError('먼저 계산 결과가 필요합니다')
    const update = toggleSurfaceLayer(layers, orbital)
    if (update.error) return setError(update.error)
    if (update.layer) upsert(update.layer)
  }
  if (!result && !reactionPath) return <p className="empty-state">계산 결과가 없으므로 표면을 만들 수 없습니다. ORCA가 없으면 명시적인 데모 결과로 UI를 시험할 수 있습니다.</p>
  const reactionMoDisabled = calculationKind === 'reaction-path' && !reactionHasWavefunctions
  return <><button className="wide surface-add" disabled={calculationKind === 'reaction-path'} onClick={() => addLayer()}><Layers3 /> 전체 전자 밀도 켜기/끄기</button><p className="help">MO의 ± 색은 확률 부호가 아니라 파동함수의 위상입니다. 최적화 경로 MO cube는 선택 시 지연 생성됩니다.</p>{reactionMoDisabled && <p className="inline-error">이 경로에는 첫 geometry의 파동함수가 없어 MO 추적을 시작할 수 없습니다.</p>}<div className="mo-list-heading">Frontier orbitals</div><div className="orbital-chips">{frontier.map(o => <button key={o.internal_id} disabled={reactionMoDisabled} className={selected === o.internal_id ? 'active' : ''} onClick={() => addLayer(o)}>{o.spin === 'alpha' ? 'α ' : o.spin === 'beta' ? 'β ' : ''}{o.label ?? `MO ${o.display_number}`}<small>{(o.energy_hartree * 27.211386).toFixed(2)} eV</small></button>)}</div><div className="mo-browser"><strong>다른 MO 불러오기</strong><select aria-label="MO 선택" disabled={reactionMoDisabled} value={extraOrbitalId} onChange={event => { setExtraOrbitalId(event.target.value); setSelected(event.target.value || undefined) }}><option value="">MO 선택</option>{availableOrbitals.map(orbital => <option key={orbital.internal_id} value={orbital.internal_id}>{orbitalOptionLabel(orbital)}</option>)}</select>{extraOrbital && <div className="mo-selection"><span>선택된 MO <b>{extraOrbital.spin === 'alpha' ? 'α ' : extraOrbital.spin === 'beta' ? 'β ' : ''}MO {extraOrbital.display_number}{extraOrbital.label ? ` · ${extraOrbital.label}` : ''}</b></span><span>에너지 <b>{(extraOrbital.energy_hartree * 27.211386245988).toFixed(2)} eV</b></span><span>점유수 <b>{extraOrbital.occupancy.toFixed(1)}</b></span><span>Spin <b>{extraOrbital.spin}</b></span></div>}<button className="wide" disabled={!extraOrbital || reactionMoDisabled} onClick={() => addLayer(extraOrbital)}><Plus /> 표면 추가</button></div>{layers.filter(layer => layer.field !== 'ao_component').map(layer => <SurfaceControl key={layer.key} layer={layer} />)}</>
}

function AOCompositionPanel({ capabilities }: { capabilities?: Capabilities }) {
  const result = useProjectStore(state => state.result)
  const selectedId = useProjectStore(state => state.selectedOrbital)
  const layers = useProjectStore(state => state.surfaces)
  const active = useProjectStore(state => state.aoMode)
  const activeOrbitalId = useProjectStore(state => state.aoOrbitalId)
  const enterMode = useProjectStore(state => state.enterAOMode)
  const exitMode = useProjectStore(state => state.exitAOMode)
  const upsert = useProjectStore(state => state.upsertSurface)
  const setError = useProjectStore(state => state.setError)
  const [composition, setComposition] = useState<OrbitalComposition>()
  const [items, setItems] = useState<BasisContribution[]>([])
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(false)
  const [localError, setLocalError] = useState<string>()
  const generation = useRef(0)
  const controller = useRef<AbortController | undefined>(undefined)
  const selected = result?.orbitals.find(orbital => orbital.internal_id === selectedId)

  const loadSurface = useCallback(async (
    orbital: Orbital,
    item: BasisContribution,
    requestGeneration: number,
    signal: AbortSignal,
  ) => {
    const layer = createBasisSurfaceLayer(orbital, item)
    upsert({ ...layer, loading: true })
    try {
      const response = await api.basisSurface(
        result!.job_id,
        orbital.spin,
        orbital.orca_index,
        item.basis_index,
        { isovalue: layer.isovalue, opacity: layer.opacity, display_mode: 'both' },
        signal,
      )
      if (!isCurrentAORequest(generation.current, requestGeneration, signal.aborted)) return
      upsert({
        ...layer,
        loading: false,
        meshUrls: response.mesh_urls,
        cacheHit: response.cache_hit,
      })
    } catch (error) {
      if (!isCurrentAORequest(generation.current, requestGeneration, signal.aborted)) return
      upsert({ ...layer, loading: false, error: (error as Error).message })
    }
  }, [result, upsert])

  const activate = useCallback(async (orbital: Orbital) => {
    if (!result) return
    if (result.demo) {
      setError('실제 ORCA 계산에서만 AO 성분을 분석할 수 있습니다.')
      return
    }
    const requestGeneration = generation.current + 1
    generation.current = requestGeneration
    controller.current?.abort()
    const nextController = new AbortController()
    controller.current = nextController
    setLoading(true)
    setLocalError(undefined)
    setComposition(undefined)
    setItems([])
    setChecked(new Set())
    const reference = {
      ...createSurfaceLayer(orbital),
      orbitalInternalId: orbital.internal_id,
    }
    enterMode(reference)
    try {
      const page = await api.composition(
        result.job_id,
        orbital.spin,
        orbital.orca_index,
        0,
        AO_PAGE_SIZE,
        nextController.signal,
      )
      if (!isCurrentAORequest(generation.current, requestGeneration, nextController.signal.aborted)) return
      setComposition(page)
      setItems(page.items)
      setChecked(initialBasisSelection(page.items))
      // orca_plot writes into the shared job directory, so initial AO generation
      // remains sequential even though the backend also serializes it per GBW.
      for (const item of page.items) {
        await loadSurface(orbital, item, requestGeneration, nextController.signal)
      }
    } catch (error) {
      if (!nextController.signal.aborted && generation.current === requestGeneration) {
        setLocalError((error as Error).message)
      }
    } finally {
      if (generation.current === requestGeneration) setLoading(false)
    }
  }, [enterMode, loadSurface, result, setError])

  const deactivate = useCallback(() => {
    generation.current += 1
    controller.current?.abort()
    controller.current = undefined
    setComposition(undefined)
    setItems([])
    setChecked(new Set())
    setLoading(false)
    setLocalError(undefined)
    exitMode()
  }, [exitMode])

  useEffect(() => {
    if (active && selected && activeOrbitalId !== selected.internal_id) void activate(selected)
  }, [active, activeOrbitalId, activate, selected])

  useEffect(() => () => {
    generation.current += 1
    controller.current?.abort()
    useProjectStore.getState().exitAOMode()
  }, [])

  const loadMore = async () => {
    if (!result || !selected || !composition?.has_more || loading) return
    const requestGeneration = generation.current
    setLoading(true)
    try {
      const page = await api.composition(
        result.job_id,
        selected.spin,
        selected.orca_index,
        items.length,
        AO_PAGE_SIZE,
        controller.current?.signal,
      )
      if (generation.current !== requestGeneration) return
      setItems(current => appendCompositionItems(current, page.items))
      setChecked(current => deselectIncomingBasis(current, page.items))
      for (const item of page.items) {
        const key = createBasisSurfaceLayer(selected, item).key
        const existing = useProjectStore.getState().surfaces.find(layer => layer.key === key)
        if (existing) upsert({ ...existing, visible: false })
      }
      setComposition(page)
    } catch (error) {
      if (generation.current === requestGeneration) setLocalError((error as Error).message)
    } finally {
      if (generation.current === requestGeneration) setLoading(false)
    }
  }

  const toggleBasis = (item: BasisContribution) => {
    if (!selected || !controller.current) return
    const isChecked = checked.has(item.basis_index)
    setChecked(current => {
      const next = new Set(current)
      if (isChecked) next.delete(item.basis_index)
      else next.add(item.basis_index)
      return next
    })
    const key = createBasisSurfaceLayer(selected, item).key
    const existing = layers.find(layer => layer.key === key)
    if (isChecked) {
      if (existing) upsert({ ...existing, visible: false })
      return
    }
    if (existing?.meshUrls && Object.keys(existing.meshUrls).length) {
      upsert({ ...existing, visible: true })
      return
    }
    void loadSurface(selected, item, generation.current, controller.current.signal)
  }

  if (!result || !selected) {
    return <p className="empty-state">에너지 도표나 MO 목록에서 오비탈을 선택하세요.</p>
  }
  return <div className="ao-composition">
    <button
      className={`wide ao-toggle ${active ? 'active' : ''}`}
      disabled={loading || (active && activeOrbitalId !== selected.internal_id)}
      onClick={() => active ? deactivate() : void activate(selected)}
    >
      {active && <CheckCircle2 />}
      {loading ? 'AO 성분 분석 중…' : 'AO 성분 표시'}
    </button>
    <p className="help ao-warning">선택 MO의 기저함수 성분 Cμ φμ입니다. 전자밀도나 독립적으로 점유된 원자 오비탈이 아닙니다.</p>
    {!capabilities?.aoComposition.available && !result.demo && (
      <p className="inline-error">{capabilities?.aoComposition.reasons.join(' · ')}</p>
    )}
    {active && localError && <p className="inline-error">{localError}</p>}
    {active && !loading && composition && !items.length && <p className="empty-state">표시할 AO 성분이 없습니다.</p>}
    {active && composition && <>
      <div className="ao-summary-heading"><b>Löwdin AO 요약</b><span>합계 100%</span></div>
      <div className="ao-groups">
        {composition.groups.map(group => <details key={group.key}>
          <summary><span>{group.atom_label}</span><span>{group.ao_label}</span><small>{group.count}개</small><b>{group.percentage.toFixed(1)}%</b><i>{group.representative_phase}</i></summary>
          {items.filter(item => group.basis_indices.includes(item.basis_index)).map(item => <div key={item.basis_index} className="ao-detail"><span>{item.shell_label}</span><code>{item.coefficient >= 0 ? '+' : ''}{item.coefficient.toFixed(3)}</code><b>{item.percentage.toFixed(1)}%</b><i>{item.phase}</i></div>)}
        </details>)}
      </div>
      <div className="ao-ranked-heading">기저함수 기여 순위</div>
      <div className="ao-ranked-list">
        {items.map(item => {
          const isChecked = checked.has(item.basis_index)
          const layer = layers.find(candidate => candidate.key === createBasisSurfaceLayer(selected, item).key)
          return <label key={item.basis_index}>
            <input type="checkbox" checked={isChecked} onChange={() => toggleBasis(item)} />
            <span><b>{item.atom_label} · {item.shell_label}</b><small>Cμ {item.coefficient >= 0 ? '+' : ''}{item.coefficient.toFixed(3)} · Löwdin {item.percentage.toFixed(1)}%</small></span>
            <i>{item.phase}</i>
            {isChecked && layer?.loading && <em>생성 중</em>}
            {isChecked && layer?.error && <em className="bad" title={layer.error}>{layer.error}</em>}
          </label>
        })}
      </div>
      {composition.has_more && <button className="wide ao-load-more" disabled={loading} onClick={() => void loadMore()}>5개 더 보기</button>}
    </>}
  </div>
}

export function RightPanel({ capabilities, job }: { capabilities?: Capabilities; job?: any }) {
  return <aside className="right-panel"><div className="panel-title"><div><strong>속성</strong><small>분자 프로젝트</small></div><Settings2 /></div><Section title="원자 추가" icon={Plus}><CoordinateInput /></Section><Section title="선택 항목" icon={AtomIcon}><SelectedAtomPanel /></Section><Section title="계산 설정" icon={FlaskConical}><CalculationSettings capabilities={capabilities} /></Section><Section title="결합과 평면" icon={Layers3} open={false}><BondsAndPlanes /></Section><Section title="전자 밀도 · MO" icon={Activity}><SurfacesPanel /></Section><Section title="AO 성분" icon={AtomIcon}><AOCompositionPanel capabilities={capabilities} /></Section>{job?.error_detail && <div className="diagnostic-error"><CircleAlert />{job.error_code}: {job.error_detail}</div>}</aside>
}
