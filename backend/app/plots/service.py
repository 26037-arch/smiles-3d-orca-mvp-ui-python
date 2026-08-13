from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import numpy as np

from ..fields import CubeFieldService
from ..jobs.manager import JobManager
from ..models import JobMode, PlotSampleRequest
from .geometry import atom_line, atom_plane, automatic_range
from .interpolation import trilinear_sample


class PlotSamplingService:
    def __init__(self, jobs: JobManager, fields: CubeFieldService, reaction_paths=None):
        self.jobs = jobs
        self.fields = fields
        self.reaction_paths = reaction_paths

    def sample(self, job_id: UUID, request: PlotSampleRequest) -> dict[str, object]:
        record = self.jobs.get(job_id)
        context = None
        if request.geometry_index is None:
            result = self.jobs.result(job_id)
        else:
            if self.reaction_paths is None:
                raise ValueError("reaction-path context is unavailable")
            context = self.reaction_paths.wavefunction_context(
                job_id, request.geometry_index
            )
            result = SimpleNamespace(
                demo=False, orbitals=context.orbitals, optimized_atoms=context.atoms
            )
        if record.mode == JobMode.DEMO or result.demo:
            raise ValueError("데모 작업에는 실제 파동함수 데이터가 없습니다")
        if request.field.field == "mo":
            orbital = next(
                (item for item in result.orbitals if item.internal_id == request.field.orbital_internal_id),
                None,
            )
            if orbital is None or (
                orbital.orca_index != request.field.orbital_index
                or orbital.spin != request.field.spin
            ):
                raise ValueError("요청한 MO 정보가 계산 결과와 일치하지 않습니다")
        job_dir = self.jobs._job_dir(job_id)
        if context is None:
            cube, cache_hit = self.fields.load(
                job_dir, request.field, resolution=request.cube_resolution
            )
        else:
            cube, cache_hit = self.fields.load_context(
                job_dir, context, request.field, resolution=request.cube_resolution
            )
        atom_lookup = {
            atom.id: np.asarray(atom.position, dtype=float) for atom in result.optimized_atoms
        }
        atoms = np.asarray([atom.position for atom in result.optimized_atoms], dtype=float)
        cut = request.cut
        if cut.kind in {"axis_line", "atom_line"}:
            if cut.kind == "axis_line":
                axis_index = {"x": 0, "y": 1, "z": 2}[cut.axis]
                direction = np.eye(3)[axis_index]
                origin = np.zeros(3)
                other = [index for index in range(3) if index != axis_index]
                origin[other] = cut.offsets
            else:
                if len(set(cut.atom_ids)) != 2 or any(i not in atom_lookup for i in cut.atom_ids):
                    raise ValueError("서로 다른 최적 구조 원자 두 개를 선택해야 합니다")
                origin, direction = atom_line(*(atom_lookup[i] for i in cut.atom_ids))
            bounds = request.bounds.s
            if request.bounds.automatic or bounds is None:
                bounds = automatic_range(atoms, origin, direction, request.bounds.padding)
            if bounds[0] >= bounds[1]:
                raise ValueError("직선 범위는 최솟값보다 최댓값이 커야 합니다")
            coordinates = np.linspace(*bounds, request.line_samples)
            points = origin + coordinates[:, None] * direction
            values, valid = trilinear_sample(cube, points)
            if not np.any(valid):
                raise ValueError("선택 범위에 유효한 Cube 표본이 없습니다")
            return {
                "kind": "line", "field": request.field.model_dump(mode="json"),
                "coordinate_label": "s", "coordinates": coordinates.tolist(),
                "values": [float(value) if ok else None for value, ok in zip(values, valid)],
                "valid": valid.tolist(), "origin": origin.tolist(),
                "direction": direction.tolist(), "bounds": {"s": list(bounds)},
                "cache_hit": cache_hit,
            }

        if cut.kind == "axis_plane":
            if cut.plane == "xy":
                origin, basis_u, basis_v = np.array([0.0, 0.0, cut.offset]), np.eye(3)[0], np.eye(3)[1]
            elif cut.plane == "yz":
                origin, basis_u, basis_v = np.array([cut.offset, 0.0, 0.0]), np.eye(3)[1], np.eye(3)[2]
            else:
                origin, basis_u, basis_v = np.array([0.0, cut.offset, 0.0]), np.eye(3)[2], np.eye(3)[0]
        else:
            if len(set(cut.atom_ids)) != 3 or any(i not in atom_lookup for i in cut.atom_ids):
                raise ValueError("서로 다른 최적 구조 원자 세 개를 선택해야 합니다")
            origin, basis_u, basis_v = atom_plane(*(atom_lookup[i] for i in cut.atom_ids))
        bounds_u, bounds_v = request.bounds.u, request.bounds.v
        if request.bounds.automatic or bounds_u is None:
            bounds_u = automatic_range(atoms, origin, basis_u, request.bounds.padding)
        if request.bounds.automatic or bounds_v is None:
            bounds_v = automatic_range(atoms, origin, basis_v, request.bounds.padding)
        if bounds_u[0] >= bounds_u[1] or bounds_v[0] >= bounds_v[1]:
            raise ValueError("평면 범위는 최솟값보다 최댓값이 커야 합니다")
        u = np.linspace(*bounds_u, request.plane_samples_u)
        v = np.linspace(*bounds_v, request.plane_samples_v)
        uu, vv = np.meshgrid(u, v, indexing="xy")
        points = origin + uu[..., None] * basis_u + vv[..., None] * basis_v
        values, valid = trilinear_sample(cube, points.reshape(-1, 3))
        if not np.any(valid):
            raise ValueError("선택 범위에 유효한 Cube 표본이 없습니다")
        shaped_values = values.reshape(len(v), len(u))
        shaped_valid = valid.reshape(len(v), len(u))
        return {
            "kind": "plane", "field": request.field.model_dump(mode="json"),
            "u_label": "u", "v_label": "v", "u": u.tolist(), "v": v.tolist(),
            "values": [[float(value) if ok else None for value, ok in zip(row, mask)] for row, mask in zip(shaped_values, shaped_valid)],
            "valid": shaped_valid.tolist(), "origin": origin.tolist(),
            "basis_u": basis_u.tolist(), "basis_v": basis_v.tolist(),
            "bounds": {"u": list(bounds_u), "v": list(bounds_v)}, "cache_hit": cache_hit,
        }
