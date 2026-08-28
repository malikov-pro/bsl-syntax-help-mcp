from __future__ import annotations

from dataclasses import dataclass

LAYER_ORDER = ("base", "8.3.25", "8.3.26", "8.3.27", "8.5.1")
NAMED_LAYERS = frozenset(LAYER_ORDER[1:])


class VersionError(ValueError):
    def __init__(self, message: str, loaded_layers: list[str]):
        super().__init__(message)
        self.loaded_layers = loaded_layers


def parse_version(raw: str) -> tuple[int, int, int]:
    text = (raw or "").strip()
    parts = text.split(".")
    if len(parts) < 2:
        raise ValueError(f"invalid version {raw!r}")
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) >= 3 else 0
    except ValueError as exc:
        raise ValueError(f"invalid version {raw!r}") from exc
    return major, minor, patch


def version_tuple_le(left: tuple[int, int, int], right: tuple[int, int, int]) -> bool:
    return left <= right


def introduced_already(introduced_in: str | None, platform_version: str) -> bool:
    if not introduced_in:
        return True
    try:
        return parse_version(introduced_in) <= parse_version(platform_version)
    except ValueError:
        return True


@dataclass(frozen=True)
class ResolvedVersion:
    platform_version: str
    membership_layer: str
    body_layers: tuple[str, ...]


def _named_layer(major: int, minor: int, patch: int) -> str | None:
    name = f"{major}.{minor}.{patch}"
    return name if name in NAMED_LAYERS else None


def resolve_platform_version(platform_version: str, committed_layers: list[str]) -> ResolvedVersion:
    loaded = sorted(committed_layers, key=lambda layer: LAYER_ORDER.index(layer) if layer in LAYER_ORDER else 99)
    try:
        major, minor, patch = parse_version(platform_version)
    except ValueError as exc:
        raise VersionError(str(exc), loaded) from exc

    named = _named_layer(major, minor, patch)
    if major == 8 and minor == 3 and 8 <= patch <= 24:
        membership = "base"
        body_layers = ("base",)
    elif named:
        membership = named
        cutoff = LAYER_ORDER.index(named)
        body_layers = LAYER_ORDER[: cutoff + 1]
    else:
        raise VersionError(
            f"Unknown platform_version {platform_version!r}",
            loaded,
        )

    if membership not in committed_layers:
        raise VersionError(
            f"Layer {membership!r} is not loaded",
            loaded,
        )
    return ResolvedVersion(
        platform_version=platform_version,
        membership_layer=membership,
        body_layers=body_layers,
    )


def pick_body_layer(available_layers: list[str], body_layers: tuple[str, ...]) -> str | None:
    allowed = [layer for layer in body_layers if layer in available_layers]
    if not allowed:
        return None
    return max(allowed, key=lambda layer: LAYER_ORDER.index(layer) if layer in LAYER_ORDER else -1)
