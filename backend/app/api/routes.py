from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from ..chemistry.diagnostics import capabilities
from ..chemistry.opi_adapter import ChemistryError
from ..chemistry.presets import PRESETS
from ..config import configure_orca_environment, load_settings, save_orca_path
from ..jobs.manager import JobManager
from ..models import JobCreate, MoleculeProject, SurfaceRequest
from ..surfaces.mesh import MESH_CACHE_VERSION
from ..surfaces.service import SurfaceService
from ..validation import validate_project


router = APIRouter(prefix="/api")


def manager(request: Request) -> JobManager:
    return request.app.state.jobs


def surfaces(request: Request) -> SurfaceService:
    return request.app.state.surfaces


def error(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": detail})


@router.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "GeoORCA local backend",
        "bind": "127.0.0.1",
        "surface_pipeline": MESH_CACHE_VERSION,
    }


@router.get("/capabilities")
def get_capabilities() -> dict[str, object]:
    return capabilities(load_settings())


class OrcaPathUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None


@router.put("/settings/orca-path")
def update_orca_path(body: OrcaPathUpdate, request: Request) -> dict[str, object]:
    if body.path:
        path = Path(body.path).expanduser()
        if not path.is_file() or path.name.lower() not in {"orca", "orca.exe"}:
            raise error(422, "INVALID_ORCA_PATH", "존재하는 orca 또는 orca.exe 파일을 선택하세요")
    save_orca_path(body.path)
    configure_orca_environment(body.path)
    manager(request).settings.orca_path = body.path
    return capabilities(load_settings())


@router.get("/presets")
def presets() -> list[dict[str, object]]:
    return list(PRESETS.values())


@router.post("/projects/validate")
def project_validate(project: MoleculeProject):
    return validate_project(project)


@router.post("/jobs", status_code=202)
def create_job(body: JobCreate, request: Request):
    try:
        return manager(request).create(body.project, body.mode)
    except ChemistryError as exc:
        raise error(422, exc.code, exc.detail) from exc


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, request: Request):
    try:
        return manager(request).get(job_id)
    except FileNotFoundError as exc:
        raise error(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다") from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, request: Request):
    try:
        return manager(request).cancel(job_id)
    except FileNotFoundError as exc:
        raise error(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다") from exc


@router.get("/jobs/{job_id}/result")
def get_result(job_id: UUID, request: Request):
    try:
        return manager(request).result(job_id)
    except FileNotFoundError as exc:
        raise error(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다") from exc
    except ChemistryError as exc:
        raise error(409, exc.code, exc.detail) from exc


@router.get("/jobs/{job_id}/orbitals")
def get_orbitals(job_id: UUID, request: Request):
    try:
        result = manager(request).result(job_id)
        return {
            "orbitals": result.orbitals,
            "homoInternalId": result.homo_internal_id,
            "lumoInternalId": result.lumo_internal_id,
        }
    except FileNotFoundError as exc:
        raise error(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다") from exc
    except ChemistryError as exc:
        raise error(409, exc.code, exc.detail) from exc


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: UUID, request: Request) -> StreamingResponse:
    jobs = manager(request)
    try:
        jobs.get(job_id)
    except FileNotFoundError as exc:
        raise error(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다") from exc

    async def stream() -> AsyncIterator[str]:
        previous = ""
        while True:
            if await request.is_disconnected():
                break
            record = jobs.get(job_id)
            logs = jobs.log_text(job_id)
            payload = json.dumps(
                {"job": record.model_dump(mode="json"), "log": logs}, ensure_ascii=False
            )
            if payload != previous:
                yield f"event: status\ndata: {payload}\n\n"
                previous = payload
            if record.state.value in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/jobs/{job_id}/surfaces")
def create_surface(job_id: UUID, body: SurfaceRequest, request: Request):
    try:
        return surfaces(request).create(job_id, body)
    except FileNotFoundError as exc:
        raise error(404, "SURFACE_SOURCE_NOT_FOUND", str(exc)) from exc
    except (IndexError, UnicodeDecodeError, ValueError, RuntimeError) as exc:
        raise error(422, "SURFACE_GENERATION_FAILED", str(exc)) from exc
    except ChemistryError as exc:
        raise error(409, exc.code, exc.detail) from exc


@router.get("/jobs/{job_id}/surfaces/{surface_id}/mesh")
def surface_mesh(job_id: UUID, surface_id: str, request: Request) -> FileResponse:
    try:
        path = surfaces(request).mesh_path(job_id, surface_id)
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=path.name,
            headers={"Cache-Control": "no-store"},
        )
    except FileNotFoundError as exc:
        raise error(404, "MESH_NOT_FOUND", "표면 메시를 찾을 수 없습니다") from exc
