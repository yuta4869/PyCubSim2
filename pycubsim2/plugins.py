from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import validate_model_path


AGENT_FORMAT_VERSION = 1


@dataclass(frozen=True)
class CameraDefinition:
    name: str = "body"
    link: str = ""
    offset: tuple[float, float, float] = (0.0, 0.0, 0.25)
    forward: tuple[float, float, float] = (1.0, 0.0, 0.0)
    up: tuple[float, float, float] = (0.0, 0.0, 1.0)
    fov_deg: float = 70.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CameraDefinition":
        return cls(
            name=str(data.get("name", "body")),
            link=str(data.get("link", "")),
            offset=tuple(float(value) for value in data.get("offset", (0.0, 0.0, 0.25))),
            forward=tuple(float(value) for value in data.get("forward", (1.0, 0.0, 0.0))),
            up=tuple(float(value) for value in data.get("up", (0.0, 0.0, 1.0))),
            fov_deg=float(data.get("fov_deg", 70.0)),
        )


@dataclass(frozen=True)
class AgentManifest:
    path: Path
    name: str
    model_path: Path
    fixed_base: bool
    scale: float
    controller_ref: str
    cameras: tuple[CameraDefinition, ...] = field(default_factory=tuple)
    spawn_position: tuple[float, float, float] = (0.0, 0.0, 0.05)
    spawn_rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "AgentManifest":
        source = Path(path).resolve()
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read agent manifest: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Agent manifest must contain a JSON object.")
        version = int(data.get("format_version", 1))
        if version > AGENT_FORMAT_VERSION:
            raise ValueError(
                f"Agent format {version} is newer than supported format {AGENT_FORMAT_VERSION}."
            )
        model_value = data.get("model")
        if isinstance(model_value, dict):
            model_file = model_value.get("path", "")
            fixed_base = bool(model_value.get("fixed_base", data.get("fixed_base", True)))
            scale = float(model_value.get("scale", data.get("scale", 1.0)))
        else:
            model_file = model_value
            fixed_base = bool(data.get("fixed_base", True))
            scale = float(data.get("scale", 1.0))
        if not model_file:
            raise ValueError("Agent manifest is missing model.path.")
        model_path = validate_model_path(source.parent / str(model_file))
        raw_cameras = data.get("cameras", [])
        if not isinstance(raw_cameras, list):
            raise ValueError("Agent cameras must be a list.")
        cameras = tuple(CameraDefinition.from_dict(item) for item in raw_cameras)
        spawn = data.get("spawn", {})
        if not isinstance(spawn, dict):
            raise ValueError("Agent spawn must be an object.")
        return cls(
            path=source,
            name=str(data.get("name", source.stem)),
            model_path=model_path,
            fixed_base=fixed_base,
            scale=scale,
            controller_ref=str(data.get("controller", "")),
            cameras=cameras,
            spawn_position=tuple(
                float(value)
                for value in spawn.get("position", (0.0, 0.0, 0.05))
            ),
            spawn_rpy_deg=tuple(
                float(value)
                for value in spawn.get("rpy_deg", (0.0, 0.0, 0.0))
            ),
            metadata=dict(data.get("metadata", {})),
        )


def load_controller(manifest: AgentManifest) -> Any | None:
    if not manifest.controller_ref:
        return None
    file_part, separator, class_name = manifest.controller_ref.partition(":")
    if not separator or not file_part or not class_name:
        raise ValueError(
            "Agent controller must use the form 'controller.py:ControllerClass'."
        )
    source = (manifest.path.parent / file_part).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Agent controller was not found: {source}")
    module_name = f"pycubsim2_agent_{source.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load controller module: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    controller_class = getattr(module, class_name, None)
    if controller_class is None:
        raise AttributeError(f"Controller class {class_name!r} was not found in {source}.")
    return controller_class()


class ControllerHost:
    def __init__(self, controller: Any | None) -> None:
        self.controller = controller
        self.running = False
        self.error = ""

    @property
    def available(self) -> bool:
        return self.controller is not None

    def start(self, api: Any) -> None:
        if self.controller is None:
            raise RuntimeError("This agent has no controller.")
        self.error = ""
        callback = getattr(self.controller, "on_start", None)
        if callback is not None:
            callback(api)
        self.running = True

    def update(self, api: Any, dt_s: float, sensors: dict[str, Any]) -> Any:
        if not self.running or self.controller is None:
            return None
        callback = getattr(self.controller, "update", None)
        if callback is None:
            return None
        try:
            return callback(api, dt_s, sensors)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.running = False
            return None

    def stop(self, api: Any) -> None:
        if self.controller is not None and self.running:
            callback = getattr(self.controller, "on_stop", None)
            if callback is not None:
                try:
                    callback(api)
                except Exception as exc:
                    self.error = f"{type(exc).__name__}: {exc}"
        self.running = False
