from __future__ import annotations

from typing import TypedDict


class Preset(TypedDict):
    id: str
    name: str
    purpose: str
    cost: str
    optimization_keywords: list[str]
    single_point_keywords: list[str]


PRESETS: dict[str, Preset] = {
    "preview": {
        "id": "preview",
        "name": "빠른 미리보기",
        "purpose": "작은 분자의 저비용 국소 구조 최적화",
        "cost": "낮음",
        "optimization_keywords": ["R2SCAN-3C", "OPT"],
        "single_point_keywords": ["R2SCAN-3C", "SP"],
    },
    "standard": {
        "id": "standard",
        "name": "표준",
        "purpose": "r²SCAN-3c 최적화 후 PBE0-D4/def2-SVP 전자구조",
        "cost": "중간",
        "optimization_keywords": ["R2SCAN-3C", "OPT"],
        "single_point_keywords": ["PBE0", "D4", "DEF2-SVP", "TIGHTSCF", "SP"],
    },
}


def get_preset(preset_id: str) -> Preset:
    try:
        return PRESETS[preset_id]
    except KeyError as exc:
        raise ValueError(f"알 수 없는 계산 프리셋: {preset_id}") from exc

