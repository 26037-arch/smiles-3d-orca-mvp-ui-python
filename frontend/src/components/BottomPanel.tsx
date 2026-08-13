import { useMemo, useState } from 'react'
import { Activity, ChevronDown, TerminalSquare } from 'lucide-react'
import { useProjectStore } from '../store/projectStore'
import { layoutEnergyLevels } from './energyDiagramLayout'

export function BottomPanel({ log }: { job?: unknown; log: string }) {
  const [collapsed, setCollapsed] = useState(false)
  const [tab, setTab] = useState<'orbitals' | 'log'>('orbitals')
  const [unit, setUnit] = useState<'eV' | 'Eh'>('eV')
  const result = useProjectStore(state => state.result)
  const selected = useProjectStore(state => state.selectedOrbital)
  const setSelected = useProjectStore(state => state.setSelectedOrbital)
  const orbitals = useMemo(() => result?.orbitals ?? [], [result?.orbitals])
  const range = useMemo(() => {
    if (!orbitals.length) return [-1, 1]
    const energies = orbitals.map(orbital => orbital.energy_hartree)
    return [Math.min(...energies), Math.max(...energies)]
  }, [orbitals])
  const layout = useMemo(() => layoutEnergyLevels(orbitals), [orbitals])
  const factor = unit === 'eV' ? 27.211386245988 : 1

  return (
    <section className={`bottom-panel ${collapsed ? 'collapsed' : ''}`}>
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
          </> : <span>계산 결과 없음</span>}
          <button className="icon-button" onClick={() => setCollapsed(!collapsed)}><ChevronDown /></button>
        </div>
      </header>
      {!collapsed && <div className="bottom-content">
        {tab === 'log' ? <pre className="job-log">{log || '로그가 없습니다.'}</pre> : orbitals.length ? (
          <div className="energy-diagram">
            <div className="energy-scroll" aria-label="MO 에너지 준위 목록">
              <div className="energy-chart" style={{ height: layout.height }}>
                <div className="energy-axis">
                  <span>{(range[1] * factor).toFixed(1)}</span>
                  <span>{(((range[0] + range[1]) / 2) * factor).toFixed(1)}</span>
                  <span>{(range[0] * factor).toFixed(1)}</span>
                  <b>{unit}</b>
                </div>
                <div className="levels">
                  {layout.levels.map(({ orbital, top, lane, laneCount }) => {
                    const gap = 2
                    const usableWidth = 86
                    const width = (usableWidth - gap * (laneCount - 1)) / laneCount
                    const left = 7 + lane * (width + gap)
                    return (
                      <button
                        key={orbital.internal_id}
                        className={`level ${orbital.occupancy ? 'occupied' : 'virtual'} ${selected === orbital.internal_id ? 'selected' : ''}`}
                        style={{ top, left: `${left}%`, width: `${width}%` }}
                        onClick={() => setSelected(orbital.internal_id)}
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
              <button onClick={() => setUnit(unit === 'eV' ? 'Eh' : 'eV')}>
                {unit} → {unit === 'eV' ? 'Eh' : 'eV'}
              </button>
            </div>
          </div>
        ) : <div className="empty-diagram">오비탈 데이터가 없습니다. 계산이 전자구조 출력을 만들지 못했거나 아직 실행되지 않았습니다.</div>}
      </div>}
    </section>
  )
}
