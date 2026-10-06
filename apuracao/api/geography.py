from __future__ import annotations

import json
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "geography"
UFS = frozenset("ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to".split())
ATTRIBUTION = "Malhas: IBGE; correspondência de códigos: Tribunal Superior Eleitoral."


def associate_features(collection: dict, uf: str, crosswalk: dict) -> dict:
    """Attach only explicit (UF, IBGE) pairs; leave unmatched geometry visible."""
    missing = 0
    for feature in collection["features"]:
        code = str(feature["properties"]["codarea"])
        entry = crosswalk.get(f"{uf}:{code}")
        feature["properties"] = {
            "id": entry["tse_code"] if entry else None,
            "name": entry["name"] if entry else f"Município IBGE {code}",
            "uf": uf,
            "ibge_code": code,
            "tse_code": entry["tse_code"] if entry else None,
        }
        missing += entry is None
    collection["reason"] = (
        f"{missing} município(s) sem correspondência oficial TSE/IBGE; consulte a tabela eleitoral."
        if missing else None
    )
    return collection


def get_geography(uf: str | None) -> dict:
    """Read prepared local assets without contacting IBGE or the electoral database."""
    key = (uf or "br").lower()
    empty = {
        "type": "FeatureCollection", "features": [], "available": False,
        "reason": None, "attribution": ATTRIBUTION, "edition": "IBGE 2020 (API v3, mínima)",
    }
    if key not in UFS and key != "br":
        empty["reason"] = "Geometria indisponível para esta UF ou exterior. Use a tabela territorial."
        return empty
    try:
        result = json.loads((ASSET_DIR / f"{key}.geojson").read_text(encoding="utf-8"))
        if result.get("type") != "FeatureCollection" or not isinstance(result.get("features"), list):
            raise ValueError("GeoJSON inválido")
        return result
    except (OSError, ValueError):
        empty["reason"] = "Base cartográfica indisponível. Execute pdm run python scripts/prepare_geography.py. Os resultados permanecem na tabela."
        return empty
