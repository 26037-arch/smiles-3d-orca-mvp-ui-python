import { useRef } from 'react'
import { ChevronDown, FileDown, FilePlus2, FolderOpen, LoaderCircle, Pause, Play, Redo2, Save, Undo2 } from 'lucide-react'
import { downloadText, parseProjectJson, projectToJson, projectToXyz, replaceFromXyz } from '../chem/serialization'
import { newProject, useProjectStore } from '../store/projectStore'
import type { Capabilities } from '../types'

export function TopBar({ capabilities, job, onRun, onCancel }: { capabilities?: Capabilities; job?: any; onRun(mode: 'orca' | 'demo'): void; onCancel(): void }) {
  const input = useRef<HTMLInputElement>(null); const state = useProjectStore()
  const busy = job && ['QUEUED', 'RUNNING'].includes(job.state)
  const open = async (file?: File) => {
    if (!file) return
    try { const text = await file.text(); state.setProject(file.name.toLowerCase().endsWith('.xyz') ? replaceFromXyz(newProject(), text) : parseProjectJson(text)) }
    catch (e) { state.setError((e as Error).message) }
  }
  return <header className="topbar">
    <div className="brand"><span className="brand-mark">G</span><div><strong>GeoORCA</strong><small>로컬 분자 스튜디오</small></div></div>
    <div className="top-actions">
      <button onClick={() => state.setProject(newProject())}><FilePlus2 /> 새 프로젝트</button>
      <button onClick={() => input.current?.click()}><FolderOpen /> 열기</button>
      <input ref={input} hidden type="file" accept=".json,.xyz" onChange={e => open(e.target.files?.[0])} />
      <div className="split-action"><button onClick={() => downloadText(`${state.project.name}.geoorca.json`, projectToJson(state.project))}><Save /> 저장</button><button aria-label="XYZ 내보내기" title="XYZ 내보내기" onClick={() => downloadText(`${state.project.name}.xyz`, projectToXyz(state.project), 'chemical/x-xyz')}><FileDown /></button></div>
      <span className="separator" />
      <button className="square" disabled={!state.history.past.length} onClick={state.undo} title="실행 취소 (Ctrl+Z)"><Undo2 /></button>
      <button className="square" disabled={!state.history.future.length} onClick={state.redo} title="다시 실행"><Redo2 /></button>
      <div className="structure-switch"><button className={state.viewStructure === 'initial' ? 'active' : ''} onClick={() => state.setViewStructure('initial')}>초기 구조</button><button disabled={!state.optimizedProject} className={state.viewStructure === 'optimized' ? 'active' : ''} onClick={() => state.setViewStructure('optimized')}>최적 구조</button></div>
    </div>
    <div className="run-actions">
      <span className={`status-pill ${job?.state?.toLowerCase() ?? 'idle'}`}>{busy && <LoaderCircle className="spin" />}{job?.state ?? 'IDLE'}{job?.progress ? ` ${Math.round(job.progress * 100)}%` : ''}</span>
      {busy ? <button className="danger" onClick={onCancel}><Pause /> 취소</button> : <>
        <button className="primary" disabled={!capabilities?.calculation.available} onClick={() => onRun('orca')} title={capabilities?.calculation.reasons.join('\n')}><Play /> ORCA 계산</button>
        {capabilities?.demo.available && <button className="demo" onClick={() => onRun('demo')}>데모 결과 <ChevronDown /></button>}
      </>}
    </div>
  </header>
}

