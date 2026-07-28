from __future__ import annotations

import hashlib
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def prepared_icub_urdf(source: str | Path) -> Path:
    """Create a cached iCub URDF with a physical root and absolute mesh paths."""

    source_path = Path(source).resolve()
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:12]
    cache_dir = Path(tempfile.gettempdir()) / "pycubsim2"
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / f"{source_path.stem}_prepared_{digest}.urdf"
    if destination.exists():
        return destination

    root = ET.parse(source_path).getroot()
    for node in list(root):
        if node.tag == "link" and node.get("name") == "world":
            root.remove(node)
        elif node.tag == "joint" and node.get("name") == "world_to_root_link_joint":
            root.remove(node)

    package_prefix = "package://iCub/"
    for mesh in root.iter("mesh"):
        filename = mesh.get("filename", "")
        if filename.startswith(package_prefix):
            mesh.set(
                "filename",
                str(source_path.parent / filename.removeprefix(package_prefix)),
            )

    temporary = destination.with_suffix(".tmp")
    ET.ElementTree(root).write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(destination)
    return destination


SUPPORTED_MODEL_SUFFIXES = {".urdf", ".sdf", ".xml", ".obj", ".stl"}


def validate_model_path(path: str | Path) -> Path:
    model_path = Path(path).resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"Model file was not found: {model_path}")
    if model_path.suffix.lower() not in SUPPORTED_MODEL_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_MODEL_SUFFIXES))
        raise ValueError(
            f"Unsupported model format {model_path.suffix!r}. Supported: {supported}"
        )
    return model_path

