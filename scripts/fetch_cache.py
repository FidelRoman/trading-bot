"""Descarga históricos y cachés FSR de un GitHub Release y verifica SHA-256."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ASSET = re.compile(r"^fsr_[a-z0-9]+_[a-z0-9]+_([0-9a-f]{16})\.npz$")
HISTORY_ASSET = re.compile(
    r"^(?P<symbol>[a-z0-9]+)_(?P<timeframe>[a-z0-9]+)_\d{8}_\d{8}\.csv$"
)


def comma_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def infer_repository() -> str:
    configured = os.getenv("GITHUB_REPOSITORY")
    if configured:
        return configured
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    match = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", remote)
    if not match:
        raise RuntimeError("no se pudo inferir owner/repo desde origin; usa --repo")
    return match.group(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset(path: Path, checksum_text: str) -> None:
    fields = checksum_text.strip().split()
    if not fields or not re.fullmatch(r"[0-9a-fA-F]{64}", fields[0]):
        raise ValueError(f"checksum inválido para {path.name}")
    if len(fields) > 1 and Path(fields[-1].lstrip("*" )).name != path.name:
        raise ValueError(f"el checksum no corresponde a {path.name}")
    actual = sha256(path)
    if actual.lower() != fields[0].lower():
        raise ValueError(f"SHA-256 incorrecto para {path.name}")


def merge_fsr_asset(source: Path, cache_dir: Path) -> Path:
    match = CACHE_ASSET.match(source.name)
    if not match:
        raise ValueError(f"nombre de caché no soportado: {source.name}")
    destination = cache_dir / f"fsr_{match.group(1)}.npz"
    with np.load(source) as data:
        incoming_keys = data["keys"]
        incoming_features = data["features"]
    if incoming_keys.ndim != 1 or incoming_features.ndim != 2:
        raise ValueError(f"estructura inválida en {source.name}")
    if len(incoming_keys) != len(incoming_features):
        raise ValueError(f"keys y features no coinciden en {source.name}")

    merged = {int(key): row for key, row in zip(incoming_keys, incoming_features)}
    if destination.exists():
        with np.load(destination) as data:
            old_keys, old_features = data["keys"], data["features"]
        for key, row in zip(old_keys, old_features):
            numeric_key = int(key)
            previous = merged.get(numeric_key)
            if previous is not None and not np.array_equal(previous, row):
                raise ValueError(f"features contradictorias para la ventana {numeric_key}")
            merged[numeric_key] = row

    destination.parent.mkdir(parents=True, exist_ok=True)
    keys = np.fromiter(merged.keys(), dtype=np.uint64, count=len(merged))
    features = np.stack([merged[int(key)] for key in keys])
    temporary = destination.with_suffix(".npz.tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, keys=keys, features=features)
    temporary.replace(destination)
    return destination


def _request_json(url: str, token: str | None) -> dict:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "trading-bot-cache",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _download(url: str, path: Path, token: str | None) -> None:
    headers = _headers(token)
    headers["Accept"] = "application/octet-stream"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request) as response, path.open("wb") as target:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)


def _selected(name: str, symbols: set[str], timeframes: set[str]) -> bool:
    history = HISTORY_ASSET.match(name)
    if history:
        return (
            (not symbols or history.group("symbol") in symbols)
            and (not timeframes or history.group("timeframe") in timeframes)
        )
    cache = CACHE_ASSET.match(name)
    if not cache:
        return False
    parts = name[:-4].split("_")
    return (not symbols or parts[1] in symbols) and (not timeframes or parts[2] in timeframes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="owner/repo; por defecto se infiere de origin")
    parser.add_argument("--tag", default="latest", help="tag del Release o 'latest'")
    parser.add_argument("--symbols", type=comma_list, default=[])
    parser.add_argument("--timeframes", type=comma_list, default=[])
    parser.add_argument("--history-only", action="store_true")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--history-dir", type=Path, default=PROJECT_ROOT / "data/history")
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_ROOT / "data/fsr_cache")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.history_only and args.cache_only:
        raise SystemExit("--history-only y --cache-only son excluyentes")
    repo = args.repo or infer_repository()
    token = os.getenv("GITHUB_TOKEN")
    suffix = "latest" if args.tag == "latest" else f"tags/{args.tag}"
    release = _request_json(f"https://api.github.com/repos/{repo}/releases/{suffix}", token)
    assets = {asset["name"]: asset for asset in release.get("assets", [])}
    symbols = {value.replace("/", "").lower() for value in args.symbols}
    timeframes = {value.lower() for value in args.timeframes}
    selected = [name for name in assets if _selected(name, symbols, timeframes)]
    if args.history_only:
        selected = [name for name in selected if HISTORY_ASSET.match(name)]
    if args.cache_only:
        selected = [name for name in selected if CACHE_ASSET.match(name)]
    if not selected:
        raise RuntimeError("el Release no contiene assets para los filtros indicados")

    with tempfile.TemporaryDirectory(prefix="tradingbot-cache-") as temp:
        temp_dir = Path(temp)
        for name in sorted(selected):
            checksum_name = f"{name}.sha256"
            if checksum_name not in assets:
                raise RuntimeError(f"falta {checksum_name} en el Release")
            local = temp_dir / name
            checksum = temp_dir / checksum_name
            _download(assets[name]["url"], local, token)
            _download(assets[checksum_name]["url"], checksum, token)
            verify_asset(local, checksum.read_text())
            if HISTORY_ASSET.match(name):
                args.history_dir.mkdir(parents=True, exist_ok=True)
                destination = args.history_dir / name
                local.replace(destination)
            else:
                destination = merge_fsr_asset(local, args.cache_dir)
            print(f"Instalado {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
