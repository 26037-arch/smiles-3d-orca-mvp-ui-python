import { Html, Line, OrbitControls, PerspectiveCamera, OrthographicCamera, TransformControls } from '@react-three/drei'
import { Canvas, type ThreeEvent, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { Pause, Play } from 'lucide-react'
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js'
import { angleDegrees, distance, normalize, stableAngleAxis, sub } from '../chem/geometry'
import { advanceOptimizationPlayback, playbackStartFrame, REACTION_PLAYBACK_FRAME_MS } from '../chem/reactionPath'
import { ELEMENTS } from '../chem/elements'
import { useProjectStore, visibleProject } from '../store/projectStore'
import type { Atom, Bond, SketchPlane, SurfaceLayer, Vec3 } from '../types'
import { WeightedBlendedOIT } from './WeightedBlendedOIT'
import { createOitSurfaceMaterial, OIT_LAYER, OIT_SURFACE_FLAG } from './weightedBlendedOitMaterial'
import { api } from '../api/client'

function BondMesh({ bond, atoms }: { bond: Bond; atoms: Atom[] }) {
  const a = atoms.find(x => x.id === bond.atomId1); const b = atoms.find(x => x.id === bond.atomId2)
  const data = useMemo(() => {
    if (!a || !b) return null; const start = new THREE.Vector3(...a.position); const end = new THREE.Vector3(...b.position)
    const midpoint = start.clone().add(end).multiplyScalar(.5); const length = start.distanceTo(end)
    const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), end.clone().sub(start).normalize())
    return { midpoint, length, quaternion }
  }, [a, b])
  if (!data) return null
  return <group position={data.midpoint} quaternion={data.quaternion}>{Array.from({ length: bond.order }, (_, i) => <mesh key={i} position={[(i - (bond.order - 1) / 2) * .1, 0, 0]}><cylinderGeometry args={[.065, .065, data.length, 18]} /><meshStandardMaterial color={bond.source === 'manual' ? '#b9c8dc' : '#75869b'} /></mesh>)}</group>
}

function AtomMesh({ atom }: { atom: Atom }) {
  const selected = useProjectStore(s => s.selection.includes(atom.id)); const select = useProjectStore(s => s.selectAtom); const tool = useProjectStore(s => s.tool)
  const productPreview = atom.id.startsWith('product-preview-')
  return <mesh position={atom.position} onPointerDown={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); select(atom.id, e.ctrlKey || e.shiftKey) }} castShadow>
    <sphereGeometry args={[Math.max(.24, ELEMENTS[atom.element].radius * .35), 32, 20]} />
    <meshStandardMaterial color={ELEMENTS[atom.element].color} transparent={productPreview} opacity={productPreview ? .48 : 1} emissive={selected || productPreview ? '#55d6ff' : '#000'} emissiveIntensity={selected ? .7 : productPreview ? .25 : 0} roughness={.3} metalness={.05} />
    {(selected || tool === 'distance' || tool === 'angle') && <Html center distanceFactor={8} position={[0, .42, 0]} className="atom-label"><span>{atom.element}</span><small>{atom.id.slice(0, 4)}</small></Html>}
  </mesh>
}

function PlaneMesh({ plane }: { plane: SketchPlane }) {
  const tool = useProjectStore(s => s.tool); const element = useProjectStore(s => s.addElement); const addAtom = useProjectStore(s => s.addAtom); const setError = useProjectStore(s => s.setError)
  const quaternion = useMemo(() => new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...plane.normal).normalize()), [plane.normal])
  const lines = useMemo(() => Array.from({ length: 25 }, (_, i) => i - 12), [])
  if (!plane.visible || !plane.valid) return null
  return <group position={plane.origin} quaternion={quaternion}>
    <mesh onPointerDown={e => { if (tool !== 'add' || !plane.active) return; e.stopPropagation(); const p = e.point.toArray() as Vec3; try { addAtom(element, p) } catch (error) { setError((error as Error).message) } }}>
      <planeGeometry args={[12, 12]} /><meshBasicMaterial color={plane.active ? '#2f8cff' : '#54687f'} transparent opacity={plane.active ? .11 : .055} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
    {lines.map(i => <Line key={`x${i}`} points={[[-6, i / 2, .003], [6, i / 2, .003]]} color={i === 0 ? '#4ea3ff' : '#31455e'} transparent opacity={i === 0 ? .7 : .24} lineWidth={i === 0 ? 1.2 : .6} />)}
    {lines.map(i => <Line key={`y${i}`} points={[[i / 2, -6, .003], [i / 2, 6, .003]]} color={i === 0 ? '#4ea3ff' : '#31455e'} transparent opacity={i === 0 ? .7 : .24} lineWidth={i === 0 ? 1.2 : .6} />)}
    <Html position={[-5.6, 5.6, .01]} className="plane-label"><span>{plane.kind}</span>{plane.active && <b>ACTIVE</b>}</Html>
  </group>
}

function DistanceMeasure({ atoms, ids }: { atoms: Atom[]; ids: string[] }) {
  const apply = useProjectStore(s => s.applyDistance); const [editing, setEditing] = useState(false)
  if (ids.length !== 2) return null; const a = atoms.find(x => x.id === ids[0]); const b = atoms.find(x => x.id === ids[1]); if (!a || !b) return null
  const d = distance(a.position, b.position); const midpoint = a.position.map((x, i) => (x + b.position[i]) / 2) as Vec3
  return <><Line points={[a.position, b.position]} color="#50d5ff" dashed dashScale={15} />
    <Html position={midpoint} center className="measure-label">{editing ? <input autoFocus defaultValue={d.toFixed(4)} onBlur={e => { apply([a.id, b.id], Number(e.target.value)); setEditing(false) }} onKeyDown={e => e.key === 'Enter' && e.currentTarget.blur()} /> : <button onClick={() => setEditing(true)}>{d.toFixed(3)} Å</button>}</Html></>
}

function AngleMeasure({ atoms, ids }: { atoms: Atom[]; ids: string[] }) {
  const apply = useProjectStore(s => s.applyAngle); const [editing, setEditing] = useState(false)
  if (ids.length !== 3) return null; const [a, b, c] = ids.map(id => atoms.find(x => x.id === id)); if (!a || !b || !c) return null
  let angle: number; try { angle = angleDegrees(a.position, b.position, c.position) } catch { return null }
  const ba = normalize(sub(a.position, b.position)); const axis = stableAngleAxis(a.position, b.position, c.position)
  const radius = Math.min(1, distance(a.position, b.position) * .55, distance(c.position, b.position) * .55); const points: Vec3[] = []
  for (let i = 0; i <= 24; i++) { const q = new THREE.Vector3(...ba).applyAxisAngle(new THREE.Vector3(...axis), -angle * Math.PI / 180 * i / 24).multiplyScalar(radius); points.push([b.position[0] + q.x, b.position[1] + q.y, b.position[2] + q.z]) }
  const label = points[12]
  return <><Line points={points} color="#ffca62" lineWidth={2} /><Html position={label} center className="measure-label angle">{editing ? <input autoFocus defaultValue={angle.toFixed(3)} onBlur={e => { apply([a.id, b.id, c.id], Number(e.target.value)); setEditing(false) }} onKeyDown={e => e.key === 'Enter' && e.currentTarget.blur()} /> : <button onClick={() => setEditing(true)}>{angle.toFixed(2)}°</button>}</Html></>
}

function SurfaceMesh({ layer, phase, url }: { layer: SurfaceLayer; phase: string; url: string }) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry>()
  const geometryRef = useRef<THREE.BufferGeometry | undefined>(undefined)
  useEffect(() => {
    let active = true
    new PLYLoader().load(url, loaded => {
      loaded.computeVertexNormals()
      if (!active) { loaded.dispose(); return }
      geometryRef.current?.dispose()
      geometryRef.current = loaded
      setGeometry(loaded)
    })
    return () => {
      active = false
      geometryRef.current?.dispose()
      geometryRef.current = undefined
    }
  }, [url])
  const color = phase === 'positive' ? layer.positiveColor : layer.negativeColor
  const [material] = useState(() => createOitSurfaceMaterial(color, layer.opacity))
  useEffect(() => {
    material.uniforms.uColor.value.set(color)
    material.uniforms.uOpacity.value = layer.opacity
  }, [color, layer.opacity, material])
  useEffect(() => () => material.dispose(), [material])
  if (!geometry) return null
  return <mesh
    geometry={geometry}
    material={material}
    ref={mesh => mesh?.layers.set(OIT_LAYER)}
    userData={{ [OIT_SURFACE_FLAG]: true }}
  />
}

function FitController({ atoms }: { atoms: Atom[] }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    const fit = () => {
      if (!atoms.length) return; const box = new THREE.Box3().setFromPoints(atoms.map(a => new THREE.Vector3(...a.position))); const sphere = new THREE.Sphere(); box.getBoundingSphere(sphere)
      camera.position.copy(sphere.center.clone().add(new THREE.Vector3(1.5, 1.1, 1.7).normalize().multiplyScalar(Math.max(5, sphere.radius * 4)))); camera.lookAt(sphere.center); camera.updateProjectionMatrix()
      const c = controls as any; if (c?.target) { c.target.copy(sphere.center); c.update() }
    }
    window.addEventListener('fit-molecule', fit); return () => window.removeEventListener('fit-molecule', fit)
  }, [atoms, camera, controls]); return null
}

function TransformGizmo({ atoms }: { atoms: Atom[] }) {
  const selection = useProjectStore(s => s.selection); const move = useProjectStore(s => s.moveAtoms); const setOrbit = useProjectStore(s => s.setOrbitEnabled)
  const group = useRef<THREE.Group>(null); const start = useRef(new THREE.Vector3())
  const center = useMemo(() => { const chosen = atoms.filter(a => selection.includes(a.id)); if (!chosen.length) return new THREE.Vector3(); return chosen.reduce((v, a) => v.add(new THREE.Vector3(...a.position)), new THREE.Vector3()).multiplyScalar(1 / chosen.length) }, [atoms, selection])
  useEffect(() => { group.current?.position.copy(center) }, [center])
  if (!selection.length) return null
  return <TransformControls mode="translate" size={.72} onMouseDown={() => { if (group.current) start.current.copy(group.current.position); setOrbit(false) }} onMouseUp={() => { if (group.current) { const d = group.current.position.clone().sub(start.current); if (d.lengthSq() > 1e-12) move(selection, d.toArray() as Vec3); group.current.position.copy(center) } setOrbit(true) }}><group ref={group} /></TransformControls>
}

function Scene() {
  const project = useProjectStore(visibleProject); const clear = useProjectStore(s => s.clearSelection); const tool = useProjectStore(s => s.tool); const toolAtoms = useProjectStore(s => s.toolAtoms); const surfaces = useProjectStore(s => s.surfaces); const orbitEnabled = useProjectStore(s => s.orbitEnabled); const reactionStatus = useProjectStore(s => s.reactionStatus)
  return <>
    <color attach="background" args={['#07111f']} /><ambientLight intensity={1.25} /><directionalLight position={[5, 8, 6]} intensity={2.2} castShadow /><directionalLight position={[-5, -3, -2]} intensity={.5} color="#4c8cff" />
    {project.displaySettings.perspective ? <PerspectiveCamera makeDefault position={[5, 4, 7]} fov={43} /> : <OrthographicCamera makeDefault position={[5, 4, 7]} zoom={75} />}
    <OrbitControls makeDefault enabled={orbitEnabled} enableDamping dampingFactor={.08} screenSpacePanning />
    <group onPointerMissed={() => clear()}>{project.sketchPlanes.map(p => <PlaneMesh key={p.id} plane={p} />)}{project.bonds.map(b => <BondMesh key={b.id} bond={b} atoms={project.atoms} />)}{project.atoms.map(a => <AtomMesh key={a.id} atom={a} />)}</group>
    {tool === 'move' && reactionStatus !== 'playing' && <TransformGizmo atoms={project.atoms} />}
    {tool === 'distance' && <DistanceMeasure atoms={project.atoms} ids={toolAtoms} />}{tool === 'angle' && <AngleMeasure atoms={project.atoms} ids={toolAtoms} />}
    {surfaces.filter(s => s.visible && !s.loading).flatMap(layer => Object.entries(layer.meshUrls).map(([phase, url]) => <SurfaceMesh key={`${layer.key}-${phase}-${url}`} layer={layer} phase={phase} url={url} />))}
    <axesHelper args={[2]} visible={project.displaySettings.showAxes} /><FitController atoms={project.atoms} /><WeightedBlendedOIT />
  </>
}

export function ReactionPathControls() {
  const calculationKind = useProjectStore(s => s.calculationKind)
  const status = useProjectStore(s => s.reactionStatus)
  const playback = useProjectStore(s => s.reactionPath)
  const frameIndex = useProjectStore(s => s.reactionFrameIndex)
  const scfIterationIndex = useProjectStore(s => s.reactionScfIterationIndex)
  const setFrame = useProjectStore(s => s.setReactionFrame)
  const setScfIteration = useProjectStore(s => s.setReactionScfIteration)
  const setPlaying = useProjectStore(s => s.setReactionPlaying)
  const error = useProjectStore(s => s.reactionError)
  const jobId = useProjectStore(s => s.project.lastCalculationId)
  const trackingEnabled = useProjectStore(s => s.trackingEnabled)
  const trackingSourceOrbital = useProjectStore(s => s.trackingSourceOrbitalId)
  const trackingSourceGeometry = useProjectStore(s => s.trackingSourceGeometryIndex)
  const trackingId = useProjectStore(s => s.trackingId)
  const trackingActive = useProjectStore(s => s.trackingActive)
  const trackingLoading = useProjectStore(s => s.trackingLoading)
  const trackingError = useProjectStore(s => s.trackingError)
  const trackingSurfaceError = useProjectStore(s => s.trackingSurfaceError)
  const completeTracking = useProjectStore(s => s.completeMoTracking)
  const failTrackingSetup = useProjectStore(s => s.failMoTrackingSetup)
  const failTrackingSurface = useProjectStore(s => s.failMoTrackingSurface)
  const [frameSurfaceLoading, setFrameSurfaceLoading] = useState(false)
  const trackingRequestRef = useRef<AbortController | undefined>(undefined)
  const trackingSurfaceRequestRef = useRef<AbortController | undefined>(undefined)
  const upsertSurface = useProjectStore(s => s.upsertSurface)
  const removeSurface = useProjectStore(s => s.removeSurface)
  const reactionIsovalue = useProjectStore(s => s.surfaces.find(layer => layer.key === 'reaction-path-mo')?.isovalue ?? 0.03)
  const requestRef = useRef<number | undefined>(undefined)
  const previousTime = useRef(0)

  useEffect(() => {
    if (status !== 'playing' || !playback) return
    const tick = (time: number) => {
      if (!previousTime.current) previousTime.current = time
      if (time - previousTime.current >= REACTION_PLAYBACK_FRAME_MS) {
        previousTime.current = time
        const state = useProjectStore.getState()
        const next = advanceOptimizationPlayback(
          playback,
          state.reactionFrameIndex,
          state.reactionScfIterationIndex,
        )
        if (next.frameIndex !== state.reactionFrameIndex) state.setReactionFrame(next.frameIndex)
        state.setReactionScfIteration(next.scfIterationIndex)
        if (!next.playing) state.setReactionPlaying(false)
      }
      if (useProjectStore.getState().reactionStatus === 'playing') requestRef.current = requestAnimationFrame(tick)
    }
    requestRef.current = requestAnimationFrame(tick)
    return () => {
      if (requestRef.current !== undefined) cancelAnimationFrame(requestRef.current)
      requestRef.current = undefined
      previousTime.current = 0
    }
  }, [status, playback])

  useEffect(() => {
    const previous = trackingRequestRef.current
    if (previous) {
      previous.abort()
      trackingRequestRef.current = undefined
    }
    if (!trackingEnabled || trackingId || !trackingSourceOrbital || trackingSourceGeometry === undefined || !jobId || !playback) return
    const controller = new AbortController(); trackingRequestRef.current = controller
    api.reactionOrbitalTrack(jobId, trackingSourceOrbital, trackingSourceGeometry, controller.signal).then(track => {
      if (trackingRequestRef.current !== controller || controller.signal.aborted) return
      completeTracking(track)
    }).catch(error => {
      if (trackingRequestRef.current !== controller || controller.signal.aborted) return
      failTrackingSetup((error as Error).message)
    })
    return () => {
      if (trackingRequestRef.current === controller) {
        trackingRequestRef.current = undefined
      }
      controller.abort()
    }
  }, [trackingEnabled, trackingId, trackingSourceOrbital, trackingSourceGeometry, jobId, playback, completeTracking, failTrackingSetup])

  useEffect(() => {
    if (calculationKind !== 'reaction-path') removeSurface('reaction-path-mo')
    return () => removeSurface('reaction-path-mo')
  }, [calculationKind, removeSurface])

  useEffect(() => {
    const frame = playback?.displayFrames[frameIndex]
    const iterations = frame ? playback?.path.images[frame.leftImageIndex]?.scfIterations?.length ?? 0 : 0
    const previous = trackingSurfaceRequestRef.current
    if (previous) {
      previous.abort()
      trackingSurfaceRequestRef.current = undefined
    }
    if (!trackingEnabled || !trackingId || !trackingSourceOrbital || !jobId || !playback || scfIterationIndex < iterations) {
      removeSurface('reaction-path-mo')
      setFrameSurfaceLoading(false)
      return
    }
    const controller = new AbortController(); trackingSurfaceRequestRef.current = controller
    setFrameSurfaceLoading(true)
    api.trackingFrameSurface(jobId, trackingId, frameIndex, reactionIsovalue, controller.signal).then(response => {
      if (trackingSurfaceRequestRef.current !== controller || controller.signal.aborted) return
      const calculated = playback.displayFrames[frameIndex].isCalculated
      upsertSurface({
        key: 'reaction-path-mo', name: calculated ? '추적 MO · 계산 geometry' : '추적 MO · 보간 표시', field: 'mo',
        orbitalInternalId: trackingSourceOrbital, spin: trackingSourceOrbital.startsWith('alpha:') ? 'alpha' : trackingSourceOrbital.startsWith('beta:') ? 'beta' : 'restricted',
        visible: true, opacity: .55, isovalue: reactionIsovalue, positiveColor: '#45b8ff', negativeColor: '#ff6a8a', meshUrls: response.meshUrls, cacheHit: response.cacheHit, reactionFrame: true,
      })
    }).catch(error => {
      if (trackingSurfaceRequestRef.current !== controller || controller.signal.aborted) return
      failTrackingSurface((error as Error).message)
    }).finally(() => {
      if (trackingSurfaceRequestRef.current === controller) {
        trackingSurfaceRequestRef.current = undefined
        setFrameSurfaceLoading(false)
      }
    })
    return () => {
      if (trackingSurfaceRequestRef.current === controller) {
        trackingSurfaceRequestRef.current = undefined
      }
      controller.abort()
    }
  }, [trackingEnabled, trackingId, trackingSourceOrbital, jobId, playback, frameIndex, scfIterationIndex, reactionIsovalue, upsertSurface, removeSurface, failTrackingSurface])

  useEffect(() => {
    const frame = playback?.displayFrames[frameIndex]
    for (const key of ['reaction-step-mo', 'reaction-step-density']) {
      const current = useProjectStore.getState().surfaces.find(layer => layer.key === key)
      if (!frame?.isCalculated || current?.reactionGeometryIndex !== frame.leftImageIndex) removeSurface(key)
    }
  }, [playback, frameIndex, removeSurface])

  if (calculationKind !== 'reaction-path') return null
  if (!playback) {
    const notFound = !error || error.startsWith('REACTION_PATH_NOT_FOUND')
    return <div className="reaction-empty" role="status">
      <strong>{notFound ? '최적화 경로 결과가 없습니다.' : '최적화 경로 결과는 있지만 형식 검증에 실패했습니다.'}</strong>
      <span>{status === 'loading-path' ? 'ORCA 구조 최적화 결과를 찾는 중입니다…' : notFound ? '현재 R0 구조로 최적화 경로 계산을 실행하세요.' : 'optimization trajectory의 원자 수, 원소 순서와 좌표를 확인하세요.'}</span>
      {error && !notFound && <em>세부 정보: {error}</em>}
    </div>
  }
  const frame = playback.displayFrames[frameIndex]
  const atEnd = frameIndex === playback.displayFrames.length - 1
  const toggle = () => {
    if (status === 'playing') return setPlaying(false)
    if (atEnd) {
      setFrame(playbackStartFrame(frameIndex, playback.displayFrames.length))
      setScfIteration(0)
    }
    setPlaying(true)
  }
  const pointText = frame.isCalculated
    ? `계산 지점 ${frame.leftImageIndex + 1}/${playback.path.images.length}`
    : `보간됨 · 지점 ${frame.leftImageIndex + 1}→${frame.rightImageIndex + 1}`
  const image = playback.path.images[frame.leftImageIndex]
  const scfIterations = image.scfIterations ?? []
  const currentScf = scfIterations[Math.max(0, scfIterationIndex - 1)]
  const hasWavefunctions = Boolean(playback.path.images[0]?.wavefunctionRef || Object.keys(playback.path.images[0]?.orbitalRefs ?? {}).length)
  const geometryEnergies = playback.path.images.map(item => item.relativeEnergyKjMol).filter((value): value is number => value != null)
  const scfEnergies = scfIterations.slice(0, scfIterationIndex).map(item => item.energyHartree).filter((value): value is number => value != null)
  const points = (values: number[]) => {
    if (!values.length) return ''
    const minimum = Math.min(...values); const span = Math.max(1e-12, Math.max(...values) - minimum)
    return values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 138 + 1},${27 - ((value - minimum) / span) * 24}`).join(' ')
  }
  return <div className="reaction-controls" aria-label="최적화 경로 재생">
    <button className="reaction-play" onClick={toggle} aria-label={status === 'playing' ? '일시정지' : '재생'}>{status === 'playing' ? <Pause /> : <Play />}</button>
    <input aria-label="최적화 경로 프레임" type="range" min="0" max={playback.displayFrames.length - 1} step="1" value={frameIndex} onChange={event => { setPlaying(false); setFrame(Number(event.target.value)) }} />
    <div className="reaction-frame-info"><strong>{pointText}</strong><span>{scfIterations.length ? `SCF ${Math.min(scfIterationIndex, scfIterations.length)}/${scfIterations.length}` : 'SCF 이력 없음'}</span></div>
    <div className="reaction-energy">{frame.isCalculated && frame.relativeEnergyKjMol != null ? `${frame.relativeEnergyKjMol.toFixed(2)} kJ/mol` : '표시 보간 · 에너지 없음'}{currentScf?.energyHartree != null && ` · SCF ${currentScf.energyHartree.toFixed(8)} Eh`}</div>
    <div className="reaction-graphs"><label>Geometry ΔE<svg viewBox="0 0 140 30"><polyline points={points(geometryEnergies)} /></svg></label><label>현재 geometry SCF<svg viewBox="0 0 140 30"><polyline points={points(scfEnergies)} /></svg></label></div>
    {!hasWavefunctions && <div className="reaction-mo-warning">이 최적화 경로에는 파동함수 결과가 없습니다. 분자 구조 경로만 재생할 수 있습니다.</div>}
    {trackingEnabled && (trackingLoading || frameSurfaceLoading) && <div className="reaction-mo-warning">명시적으로 요청한 MO Tracking을 준비하는 중…</div>}
    {(trackingError ?? trackingSurfaceError) && !trackingLoading && <div className="reaction-mo-warning">{trackingError ?? trackingSurfaceError} · 원자 경로는 계속 재생됩니다.</div>}
    {trackingEnabled && !trackingLoading && trackingActive === false && !trackingError && !trackingSurfaceError && <div className="reaction-mo-warning">대응 오비탈 없음 — 추적 종료 · 원자 경로는 계속 재생됩니다.</div>}
    <p>geometry 사이 보간은 표시 전용이며 에너지나 실제 시간으로 해석하지 않습니다.</p>
  </div>
}

export function Viewport() {
  const perspective = useProjectStore(s => s.project.displaySettings.perspective); const update = useProjectStore(s => s.updateProject); const project = useProjectStore(s => s.project)
  return <><Canvas key={perspective ? 'p' : 'o'} dpr={[1, 2]} gl={{ antialias: true, alpha: false }}><Scene /></Canvas><div className="viewport-badge"><button onClick={() => update({ displaySettings: { ...project.displaySettings, perspective: !perspective } })}>{perspective ? 'Perspective' : 'Orthographic'}</button><span>Å</span></div><ReactionPathControls /></>
}
