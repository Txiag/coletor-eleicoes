"""Prepare offline IBGE geometry and the explicit TSE/IBGE crosswalk."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from apuracao.api.geography import ASSET_DIR, ATTRIBUTION, UFS, associate_features

CROSSWALK_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/municipio_tse_ibge/municipio_tse_ibge.zip"
BASE = "https://servicodados.ibge.gov.br/api/v3/malhas"
QUERY = "formato=application/vnd.geo%2Bjson&qualidade=minima&periodo=2020"


def parse_crosswalk(raw: bytes) -> tuple[dict, dict]:
    result, states = {}, {}
    for row in csv.DictReader(io.StringIO(raw.decode("cp1252")), delimiter=";"):
        uf, ibge = row["SG_UF"].lower(), row["CD_MUNICIPIO_IBGE"]
        if uf not in UFS or not ibge.isdigit() or len(ibge) != 7:
            continue
        entry = {"tse_code": row["CD_MUNICIPIO_TSE"].zfill(5), "name": row["NM_MUNICIPIO_IBGE"],
                 "generated_at": f'{row["DT_GERACAO"]} {row["HH_GERACAO"]}'}
        key = f"{uf}:{ibge}"
        if key in result and result[key] != entry:
            raise ValueError(f"Correspondência ambígua: {key}")
        result[key] = entry
        states[row["CD_UF_IBGE"]] = {"id": uf, "uf": uf, "name": row["NM_UF"], "ibge_code": row["CD_UF_IBGE"]}
    return result, states


def ensure_prepared() -> None:
    missing_states = [uf for uf in sorted(UFS) if not (ASSET_DIR / f"{uf}.geojson").is_file()]
    base_ready = all((ASSET_DIR / name).is_file() for name in ("br.geojson", "crosswalk.json"))
    if missing_states or not base_ready:
        # O diretório pode existir após um preparo interrompido; confira os artefatos finais.
        prepare(ASSET_DIR, missing_states)


def prepare(output: Path, selected: list[str]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "sources"
    raw_dir.mkdir(exist_ok=True)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"sources": {}}

    def fetch(url: str, name: str) -> bytes:
        target = raw_dir / name
        if target.exists() and name in manifest["sources"]:
            return target.read_bytes()
        with urllib.request.urlopen(url, timeout=90) as response:
            raw = response.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        target.write_bytes(raw)
        manifest["sources"][name] = {"url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                                     "retrieved_at": datetime.now(timezone.utc).isoformat()}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return raw

    archive = fetch(CROSSWALK_URL, "municipio_tse_ibge.zip")
    raw_csv = zipfile.ZipFile(io.BytesIO(archive)).read("municipio_tse_ibge.csv")
    crosswalk, states = parse_crosswalk(raw_csv)
    (output / "crosswalk.json").write_text(json.dumps(crosswalk, ensure_ascii=False, indent=2), encoding="utf-8")

    def save(collection: dict, key: str) -> None:
        collection.update(available=True, attribution=ATTRIBUTION, edition="IBGE 2020 (API v3, mínima)")
        collection.setdefault("reason", None)
        target = output / f"{key}.geojson"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(target)
        print(f"{key}: {len(collection['features'])} geometrias; {target.stat().st_size} bytes", flush=True)

    country = json.loads(fetch(f"{BASE}/paises/BR?{QUERY}&intrarregiao=UF", "br.json"))
    for feature in country["features"]:
        feature["properties"] = states[str(feature["properties"]["codarea"])]
    save(country, "br")
    for uf in selected:
        collection = json.loads(fetch(f"{BASE}/estados/{uf.upper()}?{QUERY}&intrarregiao=municipio", f"{uf}.json"))
        geometry_keys = {f"{uf}:{feature['properties']['codarea']}" for feature in collection["features"]}
        missing_geometry = [entry["name"] for key, entry in crosswalk.items() if key.startswith(f"{uf}:") and key not in geometry_keys]
        collection = associate_features(collection, uf, crosswalk)
        if missing_geometry:
            warning = "Cadastro TSE atual sem polígono nesta edição: " + ", ".join(missing_geometry) + ". Consulte a tabela; limites municipais da edição 2020 podem diferir dos atuais."
            collection["reason"] = " ".join(filter(None, [collection["reason"], warning]))
        save(collection, uf)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uf", choices=sorted(UFS), action="append", help="Preparar somente estas UFs (padrão: todas).")
    parser.add_argument("--output", type=Path, default=ASSET_DIR)
    args = parser.parse_args()
    prepare(args.output, args.uf or sorted(UFS))
