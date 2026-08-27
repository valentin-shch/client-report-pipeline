"""Load an agency theme (name, accent colour, logo, footer) from a TOML file.

The same pipeline serves several agencies; the only thing that changes between
them is a file in reports/themes/. Logos are read off disk and inlined as
base64 data URIs so a generated report stays self-contained in an email.
"""

from __future__ import annotations

import base64
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

THEMES_DIR = Path(__file__).resolve().parent / "themes"
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str
    accent_ink: str  # text colour that sits on top of the accent
    footer: str
    logo_data_uri: str | None


def available_themes() -> list[str]:
    return sorted(p.stem for p in THEMES_DIR.glob("*.toml"))


def load_theme(name_or_path: str) -> Theme:
    path = Path(name_or_path)
    if not path.exists():
        path = THEMES_DIR / f"{name_or_path}.toml"
    if not path.exists():
        raise FileNotFoundError(
            f"no theme {name_or_path!r}; available: {', '.join(available_themes())}"
        )

    with open(path, "rb") as f:
        cfg = tomllib.load(f)

    accent = _require_hex(cfg, "accent", path)
    accent_ink = _require_hex(cfg, "accent_ink", path) if "accent_ink" in cfg else "#ffffff"

    logo_uri = None
    if cfg.get("logo"):
        logo_path = path.parent / cfg["logo"]
        if not logo_path.exists():
            raise FileNotFoundError(f"theme {path.name} points at a missing logo: {cfg['logo']}")
        logo_uri = _data_uri(logo_path)

    return Theme(
        name=cfg["name"],
        accent=accent,
        accent_ink=accent_ink,
        footer=cfg.get("footer", ""),
        logo_data_uri=logo_uri,
    )


def _require_hex(cfg: dict, key: str, path: Path) -> str:
    value = cfg.get(key)
    if not isinstance(value, str) or not _HEX.match(value):
        raise ValueError(
            f"theme {path.name}: {key!r} must be a 6-digit hex colour like #1f6f5c, got {value!r}"
        )
    return value.lower()


def _data_uri(p: Path) -> str:
    # PNG only for now; an SVG logo would need rasterising before it could be
    # embedded, since email clients won't render inline SVG.
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
