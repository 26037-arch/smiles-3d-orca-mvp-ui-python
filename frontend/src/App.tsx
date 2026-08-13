import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { api } from './api/client'
import { BottomPanel } from './components/BottomPanel'
import { DEFAULT_BOTTOM_PANEL_HEIGHT } from './components/bottomPanelResize'
import { RightPanel } from './components/RightPanel'
import { ToolRail } from './components/ToolRail'
import { TopBar } from './components/TopBar'
import { Viewport } from './components/Viewport'
import { useProjectStore } from './store/projectStore'
import type { Capabilities } from './types'
import { parseProjectJson, projectToJson } from './chem/serialization'

export default function App() {
  const [capabilities, setCapabilities] = useState<Capabilities>()
  const [job, setJob] = useState<any>()
  const [log, setLog] = useState('')
  const [bottomPanelHeight, setBottomPanelHeight] = useState(DEFAULT_BOTTOM_PANEL_HEIGHT)
  const error = useProjectStore(s => s.error); const notice = useProjectStore(s => s.notice)
  const setError = useProjectStore(s => s.setError); const setNotice = useProjectStore(s => s.setNotice)

  useEffect(() => { api.capabilities().then(setCapabilities).catch(e => setError(`백엔드 연결 실패: ${e.message}`)) }, [setError])

  useEffect(() => {
    try { const saved = localStorage.getItem('geoorca.project.v1'); if (saved) useProjectStore.getState().setProject(parseProjectJson(saved)) } catch { localStorage.removeItem('geoorca.project.v1') }
    const unsubscribe = useProjectStore.subscribe(state => localStorage.setItem('geoorca.project.v1', projectToJson(state.project)))
    const lastJob = localStorage.getItem('geoorca.lastJobId')
    let poll: number | undefined
    if (lastJob) {
      const refresh = () => api.getJob(lastJob).then(async record => {
        if (record.error_code === 'LEGACY_OUTPUT_ENCODING' || /cp949.*decode/i.test(record.error_detail ?? '')) {
          localStorage.removeItem('geoorca.lastJobId'); setJob(undefined)
          setNotice('이전 버전의 출력 인코딩 오류 작업을 지웠습니다. ORCA 계산을 다시 실행하세요.')
          if (poll) window.clearInterval(poll)
          return
        }
        setJob(record)
        if (record.state === 'SUCCEEDED') { useProjectStore.getState().applyResult(await api.result(lastJob)); if (poll) window.clearInterval(poll) }
        if (['FAILED', 'CANCELLED'].includes(record.state) && poll) window.clearInterval(poll)
      }).catch(() => { localStorage.removeItem('geoorca.lastJobId'); if (poll) window.clearInterval(poll) })
      void refresh(); poll = window.setInterval(refresh, 700)
    }
    return () => { unsubscribe(); if (poll) window.clearInterval(poll) }
  }, [setNotice])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { useProjectStore.getState().setTool('select'); useProjectStore.getState().clearSelection() }
      if (event.key === 'Delete' && !['INPUT', 'TEXTAREA', 'SELECT'].includes((event.target as HTMLElement).tagName)) useProjectStore.getState().deleteSelected()
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); if (event.shiftKey) useProjectStore.getState().redo(); else useProjectStore.getState().undo() }
    }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [])

  const run = async (mode: 'orca' | 'demo') => {
    try {
      setError(); setLog(''); const created = await api.createJob(useProjectStore.getState().project, mode); setJob(created); localStorage.setItem('geoorca.lastJobId', created.id)
      const source = new EventSource(`/api/jobs/${created.id}/events`)
      source.addEventListener('status', async event => {
        const payload = JSON.parse((event as MessageEvent).data); setJob(payload.job); setLog(payload.log)
        if (payload.job.state === 'SUCCEEDED') { source.close(); useProjectStore.getState().applyResult(await api.result(created.id)); setNotice(mode === 'demo' ? '모의 결과를 적용했습니다. 실제 양자화학 계산이 아닙니다.' : '입력 구조에서 찾은 국소 최적화 구조를 적용했습니다.') }
        if (['FAILED', 'CANCELLED'].includes(payload.job.state)) { source.close(); setError(payload.job.error_detail ?? payload.job.message) }
      })
      source.onerror = () => { source.close(); setError('계산 상태 연결이 끊겼습니다. 작업 id로 상태를 다시 조회할 수 있습니다.') }
    } catch (e) { setError((e as Error).message) }
  }
  const cancel = async () => { if (job?.id) { try { setJob(await api.cancel(job.id)) } catch (e) { setError((e as Error).message) } } }

  return <main className="app-shell" style={{ '--bottom': `${bottomPanelHeight}px` } as CSSProperties}>
    <TopBar capabilities={capabilities} job={job} onRun={run} onCancel={cancel} />
    <ToolRail />
    <section className="viewport-shell"><Viewport /></section>
    <RightPanel capabilities={capabilities} job={job} />
    <BottomPanel job={job} log={log} height={bottomPanelHeight} onHeightChange={setBottomPanelHeight} />
    {(error || notice) && <div className={`toast ${error ? 'error' : 'notice'}`} role="alert">
      {error && <AlertTriangle size={18} />}<span>{error ?? notice}</span>
      <button className="icon-button" onClick={() => { setError(); setNotice() }} aria-label="닫기"><X size={16} /></button>
    </div>}
  </main>
}
