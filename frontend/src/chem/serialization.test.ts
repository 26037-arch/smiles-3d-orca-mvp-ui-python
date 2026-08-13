import { describe, expect, it } from 'vitest'
import { newProject } from '../store/projectStore'
import { parseProjectJson, projectToJson, projectToXyz, replaceFromXyz } from './serialization'

describe('project and XYZ serialization', () => {
  it('round-trips project JSON', () => {
    const project = newProject(); project.name = 'roundtrip'
    expect(parseProjectJson(projectToJson(project))).toEqual(project)
  })
  it('imports XYZ and reinfers bonds because XYZ has no bond graph', () => {
    const text = '3\nwater\nO 0 0 0\nH .96 0 0\nH -.24 .93 0\n'
    const project = replaceFromXyz(newProject(), text)
    expect(project.atoms).toHaveLength(3); expect(project.bonds).toHaveLength(2)
    expect(projectToXyz(project).split('\n')[0]).toBe('3')
  })
})

