import type { CalculationResult, Capabilities, MoleculeProject, PlotSample, PlotSampleRequest } from '../types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, cache: 'no-store', headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail?.message ?? body?.detail
    const message = Array.isArray(detail)
      ? detail.map(item => `${item.loc?.slice(-1)?.[0] ?? '입력'}: ${item.msg}`).join(' · ')
      : detail
    throw new Error(message ?? `${response.status} ${response.statusText}`)
  }
  return response.json()
}

export const api = {
  capabilities: () => request<Capabilities>('/api/capabilities'),
  setOrcaPath: (path: string | null) => request<Capabilities>('/api/settings/orca-path', { method: 'PUT', body: JSON.stringify({ path }) }),
  presets: () => request<any[]>('/api/presets'),
  validate: (project: MoleculeProject) => request<any>('/api/projects/validate', { method: 'POST', body: JSON.stringify(project) }),
  createJob: (project: MoleculeProject, mode: 'orca' | 'demo') => request<any>('/api/jobs', { method: 'POST', body: JSON.stringify({ project, mode }) }),
  getJob: (id: string) => request<any>(`/api/jobs/${id}`),
  result: (id: string) => request<CalculationResult>(`/api/jobs/${id}/result`),
  cancel: (id: string) => request<any>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  surface: (id: string, body: any) => request<any>(`/api/jobs/${id}/surfaces`, { method: 'POST', body: JSON.stringify(body) }),
  samplePlot: (id: string, body: PlotSampleRequest) => request<PlotSample>(`/api/jobs/${id}/plots/sample`, { method: 'POST', body: JSON.stringify(body) }),
}
