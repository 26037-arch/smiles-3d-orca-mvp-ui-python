import { useEffect, useMemo, useState } from 'react'
import { Activity, Atom as AtomIcon, CheckCircle2, ChevronDown, CircleAlert, Eye, EyeOff, FlaskConical, Layers3, Plus, RefreshCcw, Settings2, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { ELEMENTS, normalizeElement } from '../chem/elements'
import { useProjectStore, visibleProject } from '../store/projectStore'
import type { Capabilities, Orbital, SurfaceLayer, Vec3 } from '../types'

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
  const [presets, setPresets] = useState<any[]>([]); useEffect(() => { api.presets().then(setPresets).catch(() => {}) }, [])
  const [orcaPath, setOrcaPath] = useState(capabilities?.orca.path ?? '')
  useEffect(() => setOrcaPath(capabilities?.orca.path ?? ''), [capabilities?.orca.path])
  const electrons = project.atoms.reduce((sum, atom) => sum + ELEMENTS[atom.element].atomicNumber, 0) - project.totalCharge
  const parityOk = electrons % 2 === (project.multiplicity - 1) % 2
  const savePath = async () => { try { await api.setOrcaPath(orcaPath.trim() || null); setNotice('ORCA 경로를 로컬 설정에 저장했습니다.'); window.setTimeout(() => window.location.reload(), 400) } catch (e) { setError((e as Error).message) } }
  return <div className="settings-grid"><label>전체 전하<input type="number" min="-20" max="20" value={project.totalCharge} onChange={e => update({ totalCharge: Number(e.target.value) })} /></label><label>스핀 다중도<input type="number" min="1" max="20" value={project.multiplicity} onChange={e => update({ multiplicity: Number(e.target.value) })} /></label><label className="full">계산 프리셋<select value={project.calculationPreset} onChange={e => update({ calculationPreset: e.target.value })}>{presets.map(p => <option key={p.id} value={p.id}>{p.name} · 비용 {p.cost}</option>)}</select></label><div className={`validation-line full ${parityOk ? 'ok' : 'bad'}`}>{parityOk ? <CheckCircle2 /> : <CircleAlert />}전자 수 {electrons} · {parityOk ? '다중도 parity 일치' : '전하·다중도 parity 불일치'}</div>{presets.filter(p => p.id === project.calculationPreset).map(p => <div key={p.id} className="preset-card full"><strong>{p.purpose}</strong><code>! {p.optimization_keywords.join(' ')}</code>{p.single_point_keywords.join(' ') !== p.optimization_keywords.join(' ') && <code>! {p.single_point_keywords.join(' ')}</code>}</div>)}<p className="help full">음이온·열린껍질·전이금속에서는 기본 프리셋이 부적절할 수 있습니다. 화학 상태를 앱이 추측하지 않습니다.</p><label className="full">ORCA 실행 파일 경로<div className="path-field"><input value={orcaPath} placeholder="C:\\Program Files\\ORCA_6.1.1\\orca.exe" onChange={e => setOrcaPath(e.target.value)} /><button onClick={savePath}>저장</button></div></label><div className="capability full"><span className={capabilities?.calculation.available ? 'dot good' : 'dot bad'} />{capabilities?.calculation.available ? `ORCA ${capabilities.orca.version} · OPI ${capabilities.opi.version}` : capabilities?.calculation.reasons.join(' · ') || '진단 중'}</div></div>
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
    if (!result || !layer.visible) return
    const timer = window.setTimeout(async () => {
      const pending = { ...layer, isovalue, loading: true, error: undefined }; upsert(pending)
      try { const response = await api.surface(result.job_id, { field: layer.field, orbital_index: layer.orbitalIndex, spin: 'restricted', isovalue, opacity: layer.opacity, display_mode: 'both' }); upsert({ ...pending, loading: false, meshUrls: response.mesh_urls, cacheHit: response.cache_hit }) }
      catch (e) { upsert({ ...pending, loading: false, error: (e as Error).message }) }
    }, 300)
    return () => window.clearTimeout(timer)
    // layer key identifies stable controls; opacity is renderer-only and intentionally excluded.
  // The layer object is replaced by upsert; primitive request inputs are the trigger.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isovalue, layer.visible, result?.job_id])
  return <div className="surface-card"><div><input type="checkbox" checked={layer.visible} onChange={e => upsert({ ...layer, visible: e.target.checked })} /><strong>{layer.name}</strong>{layer.loading && <span className="tiny-status">생성 중</span>}{layer.cacheHit && <span className="tiny-status cache">cache</span>}<button className="icon-button" onClick={() => remove(layer.key)}><Trash2 /></button></div><label>등밀도값 <input type="number" min="0.0001" step="0.005" value={isovalue} onChange={e => setIso(Math.max(.0001, Number(e.target.value)))} /></label><input aria-label="등밀도값 로그 슬라이더" type="range" min="-4" max="-0.3" step="0.02" value={Math.log10(isovalue)} onChange={e => setIso(10 ** Number(e.target.value))} /><label>투명도 <b>{layer.opacity.toFixed(2)}</b><input type="range" min="0" max="1" step="0.01" value={layer.opacity} onChange={e => upsert({ ...layer, opacity: Number(e.target.value) })} /></label>{layer.error && <p className="inline-error">{layer.error}</p>}</div>
}

function SurfacesPanel() {
  const result = useProjectStore(s => s.result); const layers = useProjectStore(s => s.surfaces); const upsert = useProjectStore(s => s.upsertSurface); const selected = useProjectStore(s => s.selectedOrbital); const setSelected = useProjectStore(s => s.setSelectedOrbital); const setError = useProjectStore(s => s.setError)
  const frontier = useMemo(() => result?.orbitals.filter(o => o.label || Math.abs(o.orca_index - (result.orbitals.find(x => x.internal_id === result.homo_internal_id)?.orca_index ?? 0)) <= 2) ?? [], [result])
  const addLayer = (orbital?: Orbital) => {
    if (!result) return setError('먼저 계산 결과가 필요합니다'); if (layers.filter(l => l.visible).length >= 6) return setError('동시에 표시할 수 있는 표면은 최대 6개입니다')
    const key = orbital ? `mo:${orbital.orca_index}` : 'total_density'; const existing = layers.find(l => l.key === key)
    upsert(existing ? { ...existing, visible: !existing.visible } : { key, name: orbital ? `${orbital.label ?? `MO ${orbital.display_number}`} · ORCA index ${orbital.orca_index}` : '전체 전자 밀도', field: orbital ? 'mo' : 'total_density', orbitalIndex: orbital?.orca_index, visible: true, opacity: .55, isovalue: orbital ? .03 : .05, positiveColor: orbital ? '#3d80ff' : '#52c9a8', negativeColor: '#ff4f87', meshUrls: {} })
    if (orbital) setSelected(orbital.internal_id)
  }
  if (!result) return <p className="empty-state">계산 결과가 없으므로 표면을 만들 수 없습니다. ORCA가 없으면 명시적인 데모 결과로 UI를 시험할 수 있습니다.</p>
  return <><button className="wide surface-add" onClick={() => addLayer()}><Layers3 /> 전체 전자 밀도 켜기/끄기</button><p className="help">MO의 ± 색은 확률 부호가 아니라 파동함수의 위상입니다. 전체 전자 밀도는 별도 scalar field입니다.</p><div className="orbital-chips">{frontier.map(o => <button key={o.internal_id} className={selected === o.internal_id ? 'active' : ''} onClick={() => addLayer(o)}>{o.label ?? `MO ${o.display_number}`}<small>{(o.energy_hartree * 27.211386).toFixed(2)} eV</small></button>)}</div>{layers.map(layer => <SurfaceControl key={layer.key} layer={layer} />)}</>
}

export function RightPanel({ capabilities, job }: { capabilities?: Capabilities; job?: any }) {
  return <aside className="right-panel"><div className="panel-title"><div><strong>속성</strong><small>분자 프로젝트</small></div><Settings2 /></div><Section title="원자 추가" icon={Plus}><CoordinateInput /></Section><Section title="선택 항목" icon={AtomIcon}><SelectedAtomPanel /></Section><Section title="계산 설정" icon={FlaskConical}><CalculationSettings capabilities={capabilities} /></Section><Section title="결합과 평면" icon={Layers3} open={false}><BondsAndPlanes /></Section><Section title="전자 밀도 · MO" icon={Activity}><SurfacesPanel /></Section>{job?.error_detail && <div className="diagnostic-error"><CircleAlert />{job.error_code}: {job.error_detail}</div>}</aside>
}
