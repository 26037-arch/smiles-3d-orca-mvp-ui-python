from __future__ import annotations

import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ..chemistry.opi_adapter import ChemistryError, OpiAdapter, _terminate_process_tree
from ..config import LocalSettings
from ..models import (
    CalculationKind,
    CalculationResult,
    JobCreate,
    JobMode,
    JobRecord,
    JobState,
    MoleculeProject,
    Orbital,
    ReactionPathSettings,
)
from ..reaction_path import ReactionPathError
from ..reaction_path.importer import ReactionPathManifestGenerator
from ..validation import validate_project


def now() -> str:
    return datetime.now(UTC).isoformat()


class JobManager:
    def __init__(self, settings: LocalSettings):
        self.settings = settings
        self.root = Path(settings.jobs_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="geoorca-job")
        self.cancel_events: dict[UUID, threading.Event] = {}
        self.processes: dict[UUID, subprocess.Popen[str]] = {}
        self.lock = threading.RLock()
        self._recover_interrupted()

    def _job_dir(self, job_id: UUID) -> Path:
        # UUID parsing happens before this method, so client text can never become a path.
        path = (self.root / str(job_id)).resolve()
        if path.parent != self.root:
            raise ValueError("invalid job path")
        return path

    def _record_path(self, job_id: UUID) -> Path:
        return self._job_dir(job_id) / "job.json"

    def _write_record(self, record: JobRecord) -> None:
        with self.lock:
            record.updated_at = now()
            destination = self._record_path(record.id)
            temporary = destination.with_name(
                f"{destination.name}.{threading.get_ident()}.tmp"
            )
            temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
            for attempt in range(8):
                try:
                    temporary.replace(destination)
                    break
                except PermissionError:
                    if attempt == 7:
                        raise
                    # Windows may briefly deny replacement while another handle
                    # is closing. Readers use the same lock; retry external locks.
                    time.sleep(0.01 * (attempt + 1))

    def _recover_interrupted(self) -> None:
        for path in self.root.glob("*/job.json"):
            try:
                record = JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if record.state in {JobState.RUNNING, JobState.QUEUED}:
                record.state = JobState.FAILED
                record.error_code = "INTERRUPTED"
                record.error_detail = "서버 재시작으로 계산이 중단되었습니다"
                record.message = "중단됨"
                self._write_record(record)
            elif (
                record.state == JobState.FAILED
                and record.error_detail
                and "cp949" in record.error_detail.lower()
                and "decode" in record.error_detail.lower()
            ):
                # Migrate failures written by the pre-UTF-8 adapter so clients do
                # not keep restoring a raw Python codec exception after upgrade.
                record.error_code = "LEGACY_OUTPUT_ENCODING"
                record.error_detail = (
                    "이전 서버의 ORCA 출력 인코딩 처리로 중단된 작업입니다. "
                    "백엔드를 재시작한 뒤 계산을 다시 실행하세요."
                )
                record.message = "이전 인코딩 오류 작업"
                self._write_record(record)

    def create_request(self, request: JobCreate) -> JobRecord:
        if request.calculation_kind == CalculationKind.SINGLE:
            if request.project is None:
                raise ChemistryError("PROJECT_REQUIRED", "단일 구조 계산에는 project가 필요합니다")
            return self.create(request.project, request.mode)
        if request.mode != JobMode.ORCA:
            raise ChemistryError(
                "REACTION_PATH_REQUIRES_ORCA", "반응 경로 계산은 실제 ORCA 모드에서만 지원합니다"
            )
        if request.reactant is None:
            raise ChemistryError("REACTANT_ENDPOINT_REQUIRED", "반응물이 필요합니다")
        if request.product is None:
            raise ChemistryError("PRODUCT_ENDPOINT_REQUIRED", "생성물이 필요합니다")
        return self.create(
            request.reactant,
            request.mode,
            calculation_kind=CalculationKind.REACTION_PATH,
            product=request.product,
            reaction_path_settings=request.reaction_path_settings,
        )

    def create(
        self,
        project: MoleculeProject,
        mode: JobMode,
        *,
        calculation_kind: CalculationKind = CalculationKind.SINGLE,
        product: MoleculeProject | None = None,
        reaction_path_settings: ReactionPathSettings | None = None,
    ) -> JobRecord:
        self._cleanup_completed_jobs()
        validation = validate_project(project)
        if not validation.valid:
            detail = "; ".join(m.message for m in validation.messages if m.level == "error")
            raise ChemistryError("INVALID_PROJECT", detail)
        if mode == JobMode.DEMO and not self.settings.demo_calculations:
            raise ChemistryError("DEMO_DISABLED", "데모 계산 모드가 비활성화되어 있습니다")
        if calculation_kind == CalculationKind.REACTION_PATH:
            if product is None:
                raise ChemistryError("PRODUCT_ENDPOINT_REQUIRED", "생성물이 필요합니다")
            self._validate_endpoints(project, product)
        job_id = uuid4()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=False)
        project_json = project.model_dump_json(indent=2, by_alias=True)
        (job_dir / "project.json").write_text(project_json, encoding="utf-8")
        if calculation_kind == CalculationKind.REACTION_PATH:
            assert product is not None
            (job_dir / "reactant-project.json").write_text(project_json, encoding="utf-8")
            (job_dir / "product-project.json").write_text(
                product.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
            )
            _write_project_xyz(job_dir / "reactant-input.xyz", project)
            _write_project_xyz(job_dir / "product-input.xyz", product)
        atom_map = {str(atom.id): index for index, atom in enumerate(project.atoms)}
        record = JobRecord(
            id=job_id, state=JobState.QUEUED, mode=mode, created_at=now(), updated_at=now(),
            message="대기 중", atom_index_map=atom_map, calculationKind=calculation_kind,
        )
        self._write_record(record)
        event = threading.Event()
        self.cancel_events[job_id] = event
        self.executor.submit(
            self._run,
            job_id,
            project,
            mode,
            event,
            calculation_kind,
            product,
            reaction_path_settings or ReactionPathSettings(),
        )
        return record

    @staticmethod
    def _validate_endpoints(reactant: MoleculeProject, product: MoleculeProject) -> None:
        if len(reactant.atoms) != len(product.atoms):
            raise ChemistryError(
                "ENDPOINT_ATOM_COUNT_MISMATCH",
                f"반응물은 {len(reactant.atoms)}개, 생성물은 {len(product.atoms)}개 원자입니다",
            )
        for index, (left, right) in enumerate(
            zip(reactant.atoms, product.atoms, strict=True), start=1
        ):
            if left.element != right.element:
                raise ChemistryError(
                    "ENDPOINT_ELEMENT_ORDER_MISMATCH",
                    f"생성물 {index}번 원자는 {right.element}이지만 반응물 {index}번 원자는 "
                    f"{left.element}입니다. 반응물과 생성물의 원자 순서를 동일하게 맞춰 주세요.",
                )
        if reactant.total_charge != product.total_charge:
            raise ChemistryError(
                "ENDPOINT_CHARGE_MISMATCH", "반응물과 생성물의 전체 전하가 다릅니다"
            )
        if reactant.multiplicity != product.multiplicity:
            raise ChemistryError(
                "ENDPOINT_MULTIPLICITY_MISMATCH", "반응물과 생성물의 다중도가 다릅니다"
            )
        validation = validate_project(product)
        if not validation.valid:
            detail = "; ".join(m.message for m in validation.messages if m.level == "error")
            raise ChemistryError("INVALID_PRODUCT_ENDPOINT", detail)
        identical = all(
            all(abs(a - b) <= 1e-12 for a, b in zip(left.position, right.position, strict=True))
            for left, right in zip(reactant.atoms, product.atoms, strict=True)
        )
        if identical:
            raise ChemistryError(
                "IDENTICAL_REACTION_ENDPOINTS", "반응물과 생성물 좌표가 동일합니다"
            )

    def _cleanup_completed_jobs(self) -> None:
        entries: list[tuple[float, Path, int]] = []
        total = 0
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            try:
                UUID(directory.name)
                record = JobRecord.model_validate_json(
                    (directory / "job.json").read_text(encoding="utf-8")
                )
                size = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
                total += size
                if record.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
                    entries.append((directory.stat().st_mtime, directory, size))
            except (OSError, ValueError):
                continue
        # Delete only server-created UUID directories with terminal jobs, oldest first.
        for _, directory, size in sorted(entries):
            if total <= self.settings.max_job_bytes:
                break
            shutil.rmtree(directory)
            total -= size

    def get(self, job_id: UUID) -> JobRecord:
        with self.lock:
            path = self._record_path(job_id)
            if not path.is_file():
                raise FileNotFoundError(str(job_id))
            return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def result(self, job_id: UUID) -> CalculationResult:
        record = self.get(job_id)
        if record.state != JobState.SUCCEEDED:
            raise ChemistryError("RESULT_NOT_READY", f"작업 상태가 {record.state}입니다")
        if record.calculation_kind == CalculationKind.REACTION_PATH:
            raise ChemistryError(
                "RESULT_NOT_AVAILABLE_FOR_REACTION_PATH",
                "반응 경로 작업은 result.json 대신 reaction-path.json을 사용합니다",
            )
        return CalculationResult.model_validate_json(
            (self._job_dir(job_id) / "result.json").read_text(encoding="utf-8")
        )

    def cancel(self, job_id: UUID) -> JobRecord:
        record = self.get(job_id)
        if record.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            return record
        if event := self.cancel_events.get(job_id):
            event.set()
        if process := self.processes.get(job_id):
            _terminate_process_tree(process)
        record.state = JobState.CANCELLED
        record.message = "취소됨"
        record.error_code = "CANCELLED"
        self._write_record(record)
        return record

    def log_text(self, job_id: UUID) -> str:
        path = self._job_dir(job_id) / "events.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def _update(self, job_id: UUID, **updates: object) -> JobRecord:
        with self.lock:
            record = self.get(job_id)
            for key, value in updates.items():
                setattr(record, key, value)
            self._write_record(record)
            return record

    def _log(self, job_id: UUID, message: str) -> None:
        with (self._job_dir(job_id) / "events.log").open("a", encoding="utf-8") as stream:
            stream.write(f"[{now()}] {message}\n")
        self._update(job_id, message=message)

    def _run(
        self,
        job_id: UUID,
        project: MoleculeProject,
        mode: JobMode,
        cancel: threading.Event,
        calculation_kind: CalculationKind = CalculationKind.SINGLE,
        product: MoleculeProject | None = None,
        reaction_path_settings: ReactionPathSettings | None = None,
    ) -> None:
        if cancel.is_set():
            return
        try:
            self._update(job_id, state=JobState.RUNNING, progress=0.05, message="시작")
            if calculation_kind == CalculationKind.REACTION_PATH:
                if not self.settings.orca_path:
                    raise ChemistryError("ORCA_UNAVAILABLE", "ORCA 경로가 설정되지 않았습니다")
                if product is None:
                    raise ChemistryError("PRODUCT_ENDPOINT_REQUIRED", "생성물이 필요합니다")
                adapter = OpiAdapter(log=lambda m: self._log(job_id, m))

                def stage(progress: float, message: str) -> None:
                    self._log(job_id, message)
                    self._update(job_id, progress=progress)

                adapter.run_reaction_path(
                    project,
                    product,
                    self._job_dir(job_id),
                    settings=reaction_path_settings or ReactionPathSettings(),
                    orca_path=self.settings.orca_path,
                    cancel_event=cancel,
                    process_started=lambda process: self.processes.__setitem__(job_id, process),
                    stage=stage,
                )
                if cancel.is_set():
                    raise ChemistryError("CANCELLED", "사용자가 계산을 취소했습니다")
                stage(0.94, "반응 경로 데이터 변환")
                try:
                    ReactionPathManifestGenerator().ensure(self._job_dir(job_id))
                except ReactionPathError as exc:
                    if exc.code == "FINAL_NEB_TRAJECTORY_MISSING":
                        raise ChemistryError(exc.code, exc.detail) from exc
                    raise ChemistryError(
                        "REACTION_PATH_MANIFEST_FAILED", f"[{exc.code}] {exc.detail}"
                    ) from exc
                self._update(job_id, state=JobState.SUCCEEDED, progress=1, message="완료")
                return
            if mode == JobMode.DEMO:
                result = self._demo(job_id, project, cancel)
            else:
                if not self.settings.orca_path:
                    raise ChemistryError("ORCA_UNAVAILABLE", "ORCA 경로가 설정되지 않았습니다")
                adapter = OpiAdapter(log=lambda m: self._log(job_id, m))
                result = adapter.run(
                    project, self._job_dir(job_id), job_id, orca_path=self.settings.orca_path,
                    cancel_event=cancel,
                    process_started=lambda process: self.processes.__setitem__(job_id, process),
                )
            if cancel.is_set():
                raise ChemistryError("CANCELLED", "사용자가 계산을 취소했습니다")
            (self._job_dir(job_id) / "result.json").write_text(
                result.model_dump_json(indent=2), encoding="utf-8"
            )
            try:
                manifest = ReactionPathManifestGenerator().generate_if_available(
                    self._job_dir(job_id)
                )
                if manifest is not None:
                    self._log(job_id, "반응 경로 manifest를 자동 생성했습니다")
            except ReactionPathError as exc:
                # A malformed optional trajectory must not turn an otherwise valid
                # electronic-structure result into a failed calculation.
                self._log(job_id, f"반응 경로 manifest 생성 건너뜀 [{exc.code}]: {exc.detail}")
            self._update(job_id, state=JobState.SUCCEEDED, progress=1, message="완료")
        except ChemistryError as exc:
            state = JobState.CANCELLED if exc.code == "CANCELLED" else JobState.FAILED
            self._update(
                job_id, state=state, message=exc.detail,
                error_code=exc.code, error_detail=exc.detail,
            )
        except UnicodeDecodeError as exc:
            self._update(
                job_id,
                state=JobState.FAILED,
                message="ORCA 출력 인코딩 오류",
                error_code="OUTPUT_ENCODING_ERROR",
                error_detail=(
                    f"{exc.encoding}으로 ORCA 출력을 읽지 못했습니다. "
                    "UTF-8 백엔드로 다시 시작한 뒤 계산을 재실행하세요."
                ),
            )
        except Exception as exc:  # job boundary: preserve structured failure on unexpected errors
            self._update(
                job_id, state=JobState.FAILED, message="내부 오류",
                error_code="INTERNAL_ERROR", error_detail=str(exc),
            )
        finally:
            self.processes.pop(job_id, None)

    def _demo(self, job_id: UUID, project: MoleculeProject, cancel: threading.Event) -> CalculationResult:
        stages = [(0.18, "데모 입력 검증"), (0.42, "데모 국소 최적화"), (0.7, "데모 오비탈 생성")]
        for progress, message in stages:
            if cancel.wait(0.08):
                raise ChemistryError("CANCELLED", "사용자가 계산을 취소했습니다")
            self._log(job_id, f"{message} (실제 ORCA 계산이 아님)")
            self._update(job_id, progress=progress)
        # Demo mode must not imply an optimization or silently alter coordinates.
        optimized = [atom.model_copy(deep=True) for atom in project.atoms]
        energies = [-1.2, -0.72, -0.48, -0.31, 0.08, 0.21, 0.43]
        occupied = max(1, min(4, (sum(_atomic_number(a.element) for a in project.atoms) - project.total_charge) // 2))
        orbitals = [
            Orbital(
                internal_id=f"restricted:{i}", orca_index=i, display_number=i + 1,
                energy_hartree=e, occupancy=2.0 if i < occupied else 0.0,
                label="HOMO" if i == occupied - 1 else "LUMO" if i == occupied else None,
            )
            for i, e in enumerate(energies)
        ]
        return CalculationResult(
            job_id=job_id, optimized_atoms=optimized, total_energy_hartree=-75.983412,
            normal_termination=True, scf_converged=True, geometry_converged=True,
            orbitals=orbitals, homo_internal_id=f"restricted:{occupied - 1}",
            lumo_internal_id=f"restricted:{occupied}", demo=True,
        )


def _atomic_number(symbol: str) -> int:
    from ..models import ATOMIC_NUMBERS

    return ATOMIC_NUMBERS[symbol]


def _write_project_xyz(path: Path, project: MoleculeProject) -> None:
    lines = [str(len(project.atoms)), project.name]
    lines.extend(
        f"{atom.element} {atom.position[0]:.12f} {atom.position[1]:.12f} "
        f"{atom.position[2]:.12f}"
        for atom in project.atoms
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
