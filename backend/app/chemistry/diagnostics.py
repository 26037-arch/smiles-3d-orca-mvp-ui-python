from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import LocalSettings


MIN_ORCA_VERSION = (6, 1, 1)


def _binary(configured: str | None, name: str) -> str | None:
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path.resolve())
    return shutil.which(name)


def _version(path: str | None) -> tuple[str | None, bool, str | None]:
    if not path:
        return None, False, "ORCA 실행 파일을 찾지 못했습니다"
    try:
        completed = subprocess.run(
            [path, "--version"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=5, shell=False
        )
        text = completed.stdout + completed.stderr
        match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
        if not match:
            return None, False, "ORCA 버전을 확인하지 못했습니다"
        parts = tuple(int(x or 0) for x in match.groups())
        version = ".".join(str(x) for x in parts)
        return version, parts >= MIN_ORCA_VERSION, None if parts >= MIN_ORCA_VERSION else "OPI 2.x에는 ORCA 6.1.1 이상이 필요합니다"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, False, f"ORCA 실행 진단 실패: {exc}"


def capabilities(settings: LocalSettings) -> dict[str, object]:
    opi_present = importlib.util.find_spec("opi") is not None
    try:
        opi_version = importlib.metadata.version("orca-pi") if opi_present else None
    except importlib.metadata.PackageNotFoundError:
        try:
            opi_version = importlib.metadata.version("opi") if opi_present else None
        except importlib.metadata.PackageNotFoundError:
            opi_version = "installed (version unknown)" if opi_present else None
    orca_path = _binary(settings.orca_path, "orca")
    version, compatible, version_error = _version(orca_path)
    orca_plot = _binary(str(Path(orca_path).with_name("orca_plot.exe")) if orca_path and os.name == "nt" else None, "orca_plot")
    jobs = Path(settings.jobs_dir).resolve()
    try:
        jobs.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=jobs, delete=True):
            writable = True
    except OSError:
        writable = False
    reasons = []
    if not opi_present:
        reasons.append("OPI 2.0을 import할 수 없습니다")
    if not orca_path:
        reasons.append("ORCA 경로가 설정되지 않았습니다")
    elif not compatible:
        reasons.append(version_error or "ORCA 버전이 호환되지 않습니다")
    if not writable:
        reasons.append("계산 작업 폴더에 쓸 수 없습니다")
    return {
        "backend": {"available": True},
        "opi": {"available": opi_present, "version": opi_version},
        "orca": {"available": bool(orca_path), "path": orca_path, "version": version, "compatible": compatible},
        "orcaPlot": {"available": bool(orca_plot), "path": orca_plot},
        "jobs": {"writable": writable, "path": str(jobs)},
        "calculation": {"available": opi_present and compatible and writable, "reasons": reasons},
        "demo": {"available": settings.demo_calculations, "label": "모의 데이터—실제 양자화학 계산이 아님"},
    }
