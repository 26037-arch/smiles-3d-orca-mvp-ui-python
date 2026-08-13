import { Atom, BoxSelect, ChartNoAxesCombined, DraftingCompass, Expand, Link2, MousePointer2, Move3d, Orbit, Plus, Ruler, Trash2 } from 'lucide-react'
import { useAnalysisStore } from '../store/analysisStore'
import { useProjectStore } from '../store/projectStore'
import type { Tool } from '../types'

const tools: { id: Tool; label: string; icon: typeof MousePointer2 }[] = [
  { id: 'select', label: '선택', icon: MousePointer2 }, { id: 'add', label: '원소 추가', icon: Plus },
  { id: 'move', label: '이동', icon: Move3d }, { id: 'plane', label: '스케치 평면', icon: BoxSelect },
  { id: 'bond-add', label: '결합 추가', icon: Link2 }, { id: 'bond-delete', label: '결합 삭제', icon: Trash2 },
  { id: 'distance', label: '길이', icon: Ruler }, { id: 'angle', label: '각도', icon: DraftingCompass },
]

export function ToolRail() {
  const tool = useProjectStore(s => s.tool); const setTool = useProjectStore(s => s.setTool)
  const toolAtoms = useProjectStore(s => s.toolAtoms); const createPlane = useProjectStore(s => s.createThreeAtomPlane)
  const result = useProjectStore(s => s.result); const analysisMode = useAnalysisStore(s => s.mode); const setAnalysisMode = useAnalysisStore(s => s.setMode)
  return <aside className="toolrail" aria-label="편집 도구">
    {tools.map(item => <button key={item.id} className={tool === item.id ? 'active' : ''} onClick={() => setTool(item.id)} title={item.label}><item.icon /><span>{item.label}</span></button>)}
    {tool === 'plane' && toolAtoms.length === 3 && <button className="confirm-tool" onClick={() => createPlane(toolAtoms)}><Atom /><span>세 원자 평면 생성</span></button>}
    <button className={analysisMode === 'plot' ? 'active' : ''} disabled={!result || result.demo} onClick={() => setAnalysisMode(analysisMode === 'plot' ? 'model' : 'plot')} title={result?.demo ? '데모 결과에는 실제 파동함수가 없습니다' : '파동함수 그래프'}><ChartNoAxesCombined /><span>파동함수</span></button>
    <span className="rail-spacer" /><button title="화면 맞춤" onClick={() => window.dispatchEvent(new CustomEvent('fit-molecule'))}><Expand /><span>화면 맞춤</span></button>
    <button title="카메라 조작: 좌클릭 회전, 우클릭 이동, 휠 확대"><Orbit /><span>카메라</span></button>
  </aside>
}
