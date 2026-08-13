from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ELEMENTS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce "
    "Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn "
    "Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr"
).split()
ATOMIC_NUMBERS = {symbol: i + 1 for i, symbol in enumerate(ELEMENTS)}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


Vec3 = tuple[float, float, float]


class Atom(StrictModel):
    id: UUID
    element: str
    position: Vec3
    label: str | None = None

    @field_validator("element")
    @classmethod
    def valid_element(cls, value: str) -> str:
        normalized = value[:1].upper() + value[1:].lower()
        if normalized not in ATOMIC_NUMBERS:
            raise ValueError(f"알 수 없는 원소 기호: {value}")
        return normalized

    @field_validator("position")
    @classmethod
    def finite_position(cls, value: Vec3) -> Vec3:
        if not all(math.isfinite(x) for x in value):
            raise ValueError("원자 좌표는 유한한 실수여야 합니다")
        return value


class Bond(StrictModel):
    id: UUID
    atom_id1: UUID = Field(alias="atomId1")
    atom_id2: UUID = Field(alias="atomId2")
    order: Literal[1, 2, 3] = 1
    source: Literal["inferred", "manual"] = "inferred"

    @model_validator(mode="after")
    def distinct_atoms(self) -> "Bond":
        if self.atom_id1 == self.atom_id2:
            raise ValueError("결합의 두 원자는 서로 달라야 합니다")
        return self


class SketchPlane(StrictModel):
    id: UUID
    kind: Literal["XY", "YZ", "ZX", "THREE_ATOMS"]
    atom_ids: list[UUID] = Field(default_factory=list, alias="atomIds")
    origin: Vec3
    normal: Vec3
    basis_u: Vec3 = Field(alias="basisU")
    basis_v: Vec3 = Field(alias="basisV")
    visible: bool = True
    active: bool = False
    valid: bool = True

    @model_validator(mode="after")
    def three_atom_count(self) -> "SketchPlane":
        if self.kind == "THREE_ATOMS" and len(set(self.atom_ids)) != 3:
            raise ValueError("세 원자 평면에는 서로 다른 원자 세 개가 필요합니다")
        return self


class DisplaySettings(StrictModel):
    perspective: bool = True
    show_grid: bool = Field(default=True, alias="showGrid")
    show_axes: bool = Field(default=True, alias="showAxes")
    atom_scale: float = Field(default=1.0, alias="atomScale")
    bond_scale: float = Field(default=1.0, alias="bondScale")


class MoleculeProject(StrictModel):
    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    name: str = "Untitled"
    atoms: list[Atom] = Field(default_factory=list)
    bonds: list[Bond] = Field(default_factory=list)
    sketch_planes: list[SketchPlane] = Field(default_factory=list, alias="sketchPlanes")
    manual_bond_exclusions: list[tuple[UUID, UUID]] = Field(
        default_factory=list, alias="manualBondExclusions"
    )
    total_charge: int = Field(default=0, alias="totalCharge", ge=-20, le=20)
    multiplicity: int = Field(default=1, ge=1, le=20)
    calculation_preset: str = Field(default="preview", alias="calculationPreset")
    display_settings: DisplaySettings = Field(
        default_factory=DisplaySettings, alias="displaySettings"
    )
    last_calculation_id: UUID | None = Field(default=None, alias="lastCalculationId")

    @model_validator(mode="after")
    def graph_integrity(self) -> "MoleculeProject":
        ids = [atom.id for atom in self.atoms]
        if len(ids) != len(set(ids)):
            raise ValueError("중복된 원자 id가 있습니다")
        valid = set(ids)
        pairs: set[frozenset[UUID]] = set()
        for bond in self.bonds:
            if bond.atom_id1 not in valid or bond.atom_id2 not in valid:
                raise ValueError("존재하지 않는 원자를 참조하는 결합이 있습니다")
            pair = frozenset((bond.atom_id1, bond.atom_id2))
            if pair in pairs:
                raise ValueError("같은 원자쌍에 중복 결합이 있습니다")
            pairs.add(pair)
        for plane in self.sketch_planes:
            if any(atom_id not in valid for atom_id in plane.atom_ids):
                raise ValueError("평면이 존재하지 않는 원자를 참조합니다")
        return self


class ValidationMessage(StrictModel):
    level: Literal["error", "warning"]
    code: str
    message: str


class ProjectValidation(StrictModel):
    valid: bool
    electron_count: int
    messages: list[ValidationMessage]


class JobMode(StrEnum):
    ORCA = "orca"
    DEMO = "demo"


class JobCreate(StrictModel):
    project: MoleculeProject
    mode: JobMode = JobMode.ORCA


class JobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobRecord(StrictModel):
    id: UUID
    state: JobState
    mode: JobMode
    created_at: str
    updated_at: str
    progress: float = 0
    message: str = ""
    error_code: str | None = None
    error_detail: str | None = None
    atom_index_map: dict[str, int] = Field(default_factory=dict)


class Orbital(StrictModel):
    internal_id: str
    orca_index: int
    display_number: int
    energy_hartree: float
    occupancy: float
    spin: Literal["restricted", "alpha", "beta"] = "restricted"
    label: str | None = None


class CalculationResult(StrictModel):
    job_id: UUID
    optimized_atoms: list[Atom]
    total_energy_hartree: float
    normal_termination: bool
    scf_converged: bool
    geometry_converged: bool
    local_minimum_notice: str = "입력 구조에서 찾은 국소 최적화 구조"
    orbitals: list[Orbital] = Field(default_factory=list)
    homo_internal_id: str | None = None
    lumo_internal_id: str | None = None
    demo: bool = False


class CalculatedAtom(StrictModel):
    element: str
    atom_index: int = Field(alias="atomIndex", ge=0)
    x: float
    y: float
    z: float

    @model_validator(mode="after")
    def finite_coordinates(self) -> "CalculatedAtom":
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("계산 지점의 원자 좌표는 유한한 수여야 합니다")
        return self


class CalculatedImage(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)
    id: str
    index: int = Field(ge=0)
    atoms: list[CalculatedAtom]
    energy_hartree: float | None = Field(default=None, alias="energyHartree")
    relative_energy_kj_mol: float | None = Field(default=None, alias="relativeEnergyKjMol")
    reaction_coordinate: float | None = Field(default=None, alias="reactionCoordinate")
    gradient: list[list[float]] | None = None
    wavefunction_ref: str | None = Field(default=None, alias="wavefunctionRef")
    orbital_refs: dict[str, str] = Field(default_factory=dict, alias="orbitalRefs")
    convergence: Literal["converged", "unconverged", "unknown"] = "unknown"

    @model_validator(mode="after")
    def finite_metadata(self) -> "CalculatedImage":
        values = (self.energy_hartree, self.relative_energy_kj_mol, self.reaction_coordinate)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("계산 지점의 에너지와 반응좌표는 유한한 수여야 합니다")
        if self.gradient is not None:
            if len(self.gradient) != len(self.atoms) or any(len(row) != 3 for row in self.gradient):
                raise ValueError("gradient는 원자마다 3개 성분을 가져야 합니다")
            if any(not math.isfinite(value) for row in self.gradient for value in row):
                raise ValueError("gradient에 NaN 또는 무한대가 있습니다")
        return self


class ReactionPathResult(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)
    schema_version: Literal[1] = Field(alias="schemaVersion")
    source_type: Literal["imported", "neb", "irc", "relaxed-scan"] = Field(alias="sourceType")
    atom_count: int = Field(alias="atomCount", ge=1)
    elements: list[str]
    charge: int | None = None
    multiplicity: int | None = Field(default=None, ge=1)
    images: list[CalculatedImage]
    has_physical_time: Literal[False] = Field(default=False, alias="hasPhysicalTime")


class DisplayFrame(StrictModel):
    index: int = Field(ge=0)
    left_image_index: int = Field(alias="leftImageIndex", ge=0)
    right_image_index: int = Field(alias="rightImageIndex", ge=0)
    interpolation_value: float = Field(alias="interpolationValue", ge=0, le=1)
    coordinates: list[Vec3]
    reaction_coordinate: float = Field(alias="reactionCoordinate", ge=0, le=1)
    relative_energy_kj_mol: float | None = Field(default=None, alias="relativeEnergyKjMol")
    is_calculated: bool = Field(alias="isCalculated")


class ReactionPathPlayback(StrictModel):
    path: ReactionPathResult
    display_frames: list[DisplayFrame] = Field(alias="displayFrames")


class OrbitalMatch(StrictModel):
    left_orbital_id: str = Field(alias="leftOrbitalId")
    right_orbital_id: str | None = Field(default=None, alias="rightOrbitalId")
    signed_overlap: float | None = Field(default=None, alias="signedOverlap")
    absolute_overlap: float | None = Field(default=None, alias="absoluteOverlap")
    status: Literal["matched", "below-threshold", "ambiguous"]


class SurfaceRequest(StrictModel):
    field: Literal["total_density", "mo"]
    orbital_index: int | None = None
    spin: Literal["restricted", "alpha", "beta"] = "restricted"
    isovalue: Annotated[float, Field(gt=0)] = 0.03
    opacity: Annotated[float, Field(ge=0, le=1)] = 0.55
    display_mode: Literal["both", "positive", "negative"] = "both"

    @model_validator(mode="after")
    def orbital_required(self) -> "SurfaceRequest":
        if self.field == "mo" and self.orbital_index is None:
            raise ValueError("MO 표면에는 orbital_index가 필요합니다")
        return self


class SurfaceRecord(StrictModel):
    id: str
    field: str
    orbital_index: int | None
    isovalue: float
    phases: list[str]
    cache_hit: bool
    mesh_urls: dict[str, str]


class BasisContribution(StrictModel):
    basis_index: int
    atom_index: int
    atom_label: str
    element: str
    ao_label: str
    shell_label: str
    coefficient: float
    loewdin_weight: float
    percentage: float
    phase: Literal["+", "-"]


class AOContributionGroup(StrictModel):
    key: str
    atom_index: int
    atom_label: str
    element: str
    ao_label: str
    basis_indices: list[int]
    count: int
    percentage: float
    representative_phase: Literal["+", "-"]


class OrbitalComposition(StrictModel):
    orbital_internal_id: str
    energy_hartree: float
    population_method: Literal["loewdin"] = "loewdin"
    interpretation: str = "selected_mo_basis_component"
    items: list[BasisContribution]
    groups: list[AOContributionGroup]
    offset: int
    limit: int
    total: int
    has_more: bool
    cache_hit: bool = False


class BasisSurfaceRequest(StrictModel):
    isovalue: Annotated[float, Field(gt=0)] = 0.03
    opacity: Annotated[float, Field(ge=0, le=1)] = 0.55
    display_mode: Literal["both", "positive", "negative"] = "both"


class PlotField(StrictModel):
    field: Literal["mo", "total_density"]
    orbital_internal_id: str | None = None
    orbital_index: int | None = None
    spin: Literal["restricted", "alpha", "beta"] = "restricted"

    @model_validator(mode="after")
    def field_metadata(self) -> "PlotField":
        if self.field == "mo" and (
            self.orbital_internal_id is None or self.orbital_index is None
        ):
            raise ValueError("MO 그래프에는 orbital_internal_id와 orbital_index가 필요합니다")
        if self.field == "total_density" and (
            self.orbital_internal_id is not None or self.orbital_index is not None
        ):
            raise ValueError("전체 전자밀도에는 오비탈 정보를 지정할 수 없습니다")
        return self


class AxisLineCut(StrictModel):
    kind: Literal["axis_line"]
    axis: Literal["x", "y", "z"]
    offsets: tuple[float, float] = (0.0, 0.0)


class AtomLineCut(StrictModel):
    kind: Literal["atom_line"]
    atom_ids: tuple[UUID, UUID]


class AxisPlaneCut(StrictModel):
    kind: Literal["axis_plane"]
    plane: Literal["xy", "yz", "zx"]
    offset: float = 0.0


class AtomPlaneCut(StrictModel):
    kind: Literal["atom_plane"]
    atom_ids: tuple[UUID, UUID, UUID]


class PlotBounds(StrictModel):
    automatic: bool = True
    padding: Annotated[float, Field(ge=0, le=20)] = 2.0
    s: tuple[float, float] | None = None
    u: tuple[float, float] | None = None
    v: tuple[float, float] | None = None


class PlotSampleRequest(StrictModel):
    field: PlotField
    cut: AxisLineCut | AtomLineCut | AxisPlaneCut | AtomPlaneCut
    bounds: PlotBounds = Field(default_factory=PlotBounds)
    line_samples: Annotated[int, Field(ge=32, le=4096)] = 512
    plane_samples_u: Annotated[int, Field(ge=16, le=256)] = 96
    plane_samples_v: Annotated[int, Field(ge=16, le=256)] = 96
    cube_resolution: Annotated[int, Field(ge=20, le=100)] = 40
