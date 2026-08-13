import type { CalculationResult, Capabilities, JobCreateRequest, JobRecord, MoleculeProject, OrbitalComposition, OrbitalSpin, PlotSample, PlotSampleRequest, ReactionPathPlayback } from '../types'

export function apiErrorMessage(body: any, status: number, statusText: string): string {
  const detail = body?.detail?.message ?? body?.detail
  const code = body?.detail?.code
  const message = Array.isArray(detail)
    ? detail.map(item => `${item.loc?.slice(-1)?.[0] ?? '입력'}: ${item.msg}`).join(' · ')
    : detail
  if (code && message) return `${code}: ${message}`
  return message ?? `${status} ${statusText}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, cache: 'no-store', headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(apiErrorMessage(body, response.status, response.statusText))
  }
  return response.json()
}

export const api = {
  capabilities: () => request<Capabilities>('/api/capabilities'),
  setOrcaPath: (path: string | null) => request<Capabilities>('/api/settings/orca-path', { method: 'PUT', body: JSON.stringify({ path }) }),
  presets: () => request<any[]>('/api/presets'),
  validate: (project: MoleculeProject) => request<any>('/api/projects/validate', { method: 'POST', body: JSON.stringify(project) }),
  createJob: (body: JobCreateRequest) => request<JobRecord>('/api/jobs', { method: 'POST', body: JSON.stringify(body) }),
  getJob: (id: string) => request<JobRecord>(`/api/jobs/${id}`),
  result: (id: string) => request<CalculationResult>(`/api/jobs/${id}/result`),
  reactionPath: (id: string, signal?: AbortSignal) => request<ReactionPathPlayback>(`/api/jobs/${id}/reaction-path`, { signal }),
  reactionOrbitalTrack: (id: string, orbitalId: string, isovalue = 0.03, signal?: AbortSignal) => request<{ orbitalId: string; threshold: number; active: boolean; steps: Array<{ leftImageIndex: number; rightImageIndex: number; match: import('../types').OrbitalMatch; phaseSign: number }>; frameSurfaces: Record<string, Record<string, string>> }>(`/api/jobs/${id}/reaction-path/orbitals/track`, { method: 'POST', body: JSON.stringify({ orbital_id: orbitalId, isovalue }), signal }),
  cancel: (id: string) => request<JobRecord>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  surface: (id: string, body: any) => request<any>(`/api/jobs/${id}/surfaces`, { method: 'POST', body: JSON.stringify(body) }),
  composition: (id: string, spin: OrbitalSpin, orcaIndex: number, offset = 0, limit = 5, signal?: AbortSignal) => request<OrbitalComposition>(`/api/jobs/${id}/orbitals/${spin}/${orcaIndex}/composition?offset=${offset}&limit=${limit}`, { signal }),
  basisSurface: (id: string, spin: OrbitalSpin, orcaIndex: number, basisIndex: number, body: any, signal?: AbortSignal) => request<any>(`/api/jobs/${id}/orbitals/${spin}/${orcaIndex}/basis/${basisIndex}/surface`, { method: 'POST', body: JSON.stringify(body), signal }),
  samplePlot: (id: string, body: PlotSampleRequest) => request<PlotSample>(`/api/jobs/${id}/plots/sample`, { method: 'POST', body: JSON.stringify(body) }),
}
