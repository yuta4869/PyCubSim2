from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCENE_FORMAT_VERSION = 1
ENTITY_KINDS = {"pycub", "table", "primitive", "model", "agent"}
PRIMITIVE_SHAPES = {"box", "sphere", "cylinder"}


def new_entity_id(kind: str) -> str:
    prefix = "".join(character for character in kind.lower() if character.isalnum())
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def normalized_angle(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Angles must be finite numbers.")
    normalized = (value + 180.0) % 360.0 - 180.0
    if math.isclose(normalized, -180.0) and value > 0.0:
        return 180.0
    return normalized


def finite_value(name: str, value: float, lower: float, upper: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    if not lower <= value <= upper:
        raise ValueError(f"{name} must be between {lower:g} and {upper:g}.")
    return value


def validated_color(values: tuple[float, float, float, float] | list[float]) -> tuple[float, float, float, float]:
    if len(values) not in (3, 4):
        raise ValueError("Color must contain RGB or RGBA values.")
    rgba = [finite_value("Color", value, 0.0, 1.0) for value in values]
    if len(rgba) == 3:
        rgba.append(1.0)
    return tuple(rgba)


@dataclass
class Transform:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

    def validated(self) -> "Transform":
        return Transform(
            x=finite_value("X", self.x, -20.0, 20.0),
            y=finite_value("Y", self.y, -20.0, 20.0),
            z=finite_value("Z", self.z, -5.0, 20.0),
            roll_deg=normalized_angle(self.roll_deg),
            pitch_deg=normalized_angle(self.pitch_deg),
            yaw_deg=normalized_angle(self.yaw_deg),
        )


@dataclass
class SensorOptions:
    camera_mount: str = "left_eye"
    rgb: bool = True
    depth: bool = True
    segmentation: bool = False
    joints: bool = True
    imu: bool = True
    contact: bool = True
    lidar: bool = False

    def validated(self) -> "SensorOptions":
        mount = str(self.camera_mount).strip() or "body"
        return SensorOptions(
            camera_mount=mount,
            rgb=bool(self.rgb),
            depth=bool(self.depth),
            segmentation=bool(self.segmentation),
            joints=bool(self.joints),
            imu=bool(self.imu),
            contact=bool(self.contact),
            lidar=bool(self.lidar),
        )


@dataclass
class EntitySpec:
    entity_id: str
    name: str
    kind: str
    transform: Transform = field(default_factory=Transform)
    fixed_base: bool = True
    scale: float = 1.0
    model_path: str = ""
    manifest_path: str = ""
    primitive_shape: str = "box"
    size: tuple[float, float, float] = (0.16, 0.16, 0.16)
    mass: float = 0.0
    color: tuple[float, float, float, float] = (0.82, 0.18, 0.12, 1.0)
    behavior: str = "Manual pose"
    sensors: SensorOptions = field(default_factory=SensorOptions)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validated(self) -> "EntitySpec":
        kind = str(self.kind).strip().lower()
        if kind not in ENTITY_KINDS:
            raise ValueError(f"Unsupported entity kind: {self.kind}")
        entity_id = str(self.entity_id).strip()
        if not entity_id:
            raise ValueError("Entity ID cannot be empty.")
        name = str(self.name).strip()
        if not name:
            raise ValueError("Entity name cannot be empty.")
        shape = str(self.primitive_shape).strip().lower()
        if shape not in PRIMITIVE_SHAPES:
            raise ValueError(f"Unsupported primitive shape: {shape}")
        if len(self.size) != 3:
            raise ValueError("Entity size must contain X, Y and Z.")
        size = tuple(
            finite_value("Entity size", value, 0.005, 10.0) for value in self.size
        )
        return EntitySpec(
            entity_id=entity_id,
            name=name,
            kind=kind,
            transform=self.transform.validated(),
            fixed_base=bool(self.fixed_base),
            scale=finite_value("Scale", self.scale, 0.001, 100.0),
            model_path=str(self.model_path),
            manifest_path=str(self.manifest_path),
            primitive_shape=shape,
            size=size,
            mass=finite_value("Mass", self.mass, 0.0, 10_000.0),
            color=validated_color(self.color),
            behavior=str(self.behavior).strip() or "Manual pose",
            sensors=self.sensors.validated(),
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.validated())

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        base_dir: str | Path | None = None,
    ) -> "EntitySpec":
        if not isinstance(data, dict):
            raise ValueError("Entity data must be a JSON object.")
        values = dict(data)
        values["transform"] = Transform(**values.get("transform", {}))
        values["sensors"] = SensorOptions(**values.get("sensors", {}))
        if "size" in values:
            values["size"] = tuple(values["size"])
        if "color" in values:
            values["color"] = tuple(values["color"])
        if base_dir is not None:
            base = Path(base_dir)
            for key in ("model_path", "manifest_path"):
                raw = str(values.get(key, ""))
                if raw and not Path(raw).is_absolute():
                    values[key] = str((base / raw).resolve())
        try:
            return cls(**values).validated()
        except TypeError as exc:
            raise ValueError(f"Invalid entity fields: {exc}") from exc


@dataclass
class SceneConfig:
    entities: list[EntitySpec]
    gravity: float = -9.81
    physics_hz: int = 240
    control_hz: int = 60
    format_version: int = SCENE_FORMAT_VERSION

    def validated(self) -> "SceneConfig":
        entities = [entity.validated() for entity in self.entities]
        ids = [entity.entity_id for entity in entities]
        if len(ids) != len(set(ids)):
            raise ValueError("Entity IDs must be unique.")
        return SceneConfig(
            entities=entities,
            gravity=finite_value("Gravity", self.gravity, -100.0, 100.0),
            physics_hz=int(finite_value("Physics Hz", self.physics_hz, 30, 1000)),
            control_hz=int(finite_value("Control Hz", self.control_hz, 1, 240)),
            format_version=SCENE_FORMAT_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        config = self.validated()
        return {
            "format_version": config.format_version,
            "gravity": config.gravity,
            "physics_hz": config.physics_hz,
            "control_hz": config.control_hz,
            "entities": [entity.to_dict() for entity in config.entities],
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        base_dir: str | Path | None = None,
    ) -> "SceneConfig":
        if not isinstance(data, dict):
            raise ValueError("Scene file must contain a JSON object.")
        version = int(data.get("format_version", 1))
        if version > SCENE_FORMAT_VERSION:
            raise ValueError(
                f"Scene format {version} is newer than supported format {SCENE_FORMAT_VERSION}."
            )
        raw_entities = data.get("entities")
        if not isinstance(raw_entities, list):
            raise ValueError("Scene file must contain an entities list.")
        return cls(
            entities=[
                EntitySpec.from_dict(entity, base_dir=base_dir)
                for entity in raw_entities
            ],
            gravity=data.get("gravity", -9.81),
            physics_hz=data.get("physics_hz", 240),
            control_hz=data.get("control_hz", 60),
            format_version=version,
        ).validated()

    @classmethod
    def load(cls, path: str | Path) -> "SceneConfig":
        source = Path(path).resolve()
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read scene: {exc}") from exc
        return cls.from_dict(data, base_dir=source.parent)

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def default_scene() -> SceneConfig:
    return SceneConfig(
        entities=[
            EntitySpec(
                entity_id="pycub_1",
                name="PyCub 1",
                kind="pycub",
                transform=Transform(x=0.0, y=0.0, z=0.65, yaw_deg=180.0),
                fixed_base=True,
                behavior="Manual pose",
                sensors=SensorOptions(
                    camera_mount="left_eye",
                    rgb=True,
                    depth=True,
                    segmentation=False,
                    joints=True,
                    imu=True,
                    contact=True,
                    lidar=False,
                ),
            ),
            EntitySpec(
                entity_id="table_1",
                name="Table 1",
                kind="table",
                transform=Transform(x=-0.55, y=0.0, z=0.0),
                fixed_base=True,
                size=(0.72, 1.05, 0.525),
                mass=0.0,
                color=(0.68, 0.40, 0.18, 1.0),
                sensors=SensorOptions(
                    camera_mount="body",
                    rgb=False,
                    depth=False,
                    segmentation=False,
                    joints=False,
                    imu=False,
                    contact=False,
                    lidar=False,
                ),
            ),
        ]
    ).validated()
