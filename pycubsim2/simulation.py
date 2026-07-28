from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pybullet as p

from .actions import (
    BUILTIN_BEHAVIORS,
    DEFAULT_POSE_DEG,
    KeyframeAction,
    RandomBehavior,
    behavior_targets,
    finger_closed_value,
    home_targets,
)
from .config import (
    EntitySpec,
    SceneConfig,
    SensorOptions,
    Transform,
    default_scene,
    new_entity_id,
)
from .model import prepared_icub_urdf, validate_model_path
from .plugins import AgentManifest, CameraDefinition, ControllerHost, load_controller
from .sensors import SensorFrame, depth_colormap, segmentation_colormap


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ICUB_URDF = PROJECT_ROOT / "assets" / "iCub" / "full.urdf"


@dataclass
class EntityRuntime:
    spec: EntitySpec
    body_ids: list[int]
    primary_body: int
    relative_body_poses: dict[
        int, tuple[tuple[float, float, float], tuple[float, float, float, float]]
    ] = field(default_factory=dict)
    base_inertial_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    base_inertial_orientation: tuple[float, float, float, float] = (
        0.0,
        0.0,
        0.0,
        1.0,
    )
    joints: dict[str, int] = field(default_factory=dict)
    links: dict[str, int] = field(default_factory=dict)
    movable_joint_ids: list[int] = field(default_factory=list)
    q_index_joint_ids: list[int] = field(default_factory=list)
    joint_limits: dict[int, tuple[float, float]] = field(default_factory=dict)
    target_positions: dict[int, float] = field(default_factory=dict)
    applied_positions: dict[int, float] = field(default_factory=dict)
    motor_forces: list[float] = field(default_factory=list)
    motor_position_gains: list[float] = field(default_factory=list)
    motor_settle_steps: int = 0
    manual_deg: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_POSE_DEG))
    left_grip: float = 0.0
    right_grip: float = 0.0
    behavior_running: bool = False
    behavior_elapsed_s: float = 0.0
    behavior_speed: float = 1.0
    behavior_intensity: float = 0.55
    random_behavior: RandomBehavior | None = None
    keyframe_action: KeyframeAction | None = None
    manifest: AgentManifest | None = None
    controller_host: ControllerHost | None = None
    controller_api: "AgentAPI | None" = None
    last_controller_output: Any = None


class AgentAPI:
    """Narrow runtime API passed to imported local agent controllers."""

    def __init__(self, simulation: "PyCubSim2Simulation", entity_id: str) -> None:
        self._simulation = simulation
        self.entity_id = entity_id

    @property
    def simulation_time(self) -> float:
        return self._simulation.elapsed_s

    def get_pose(self) -> dict[str, tuple[float, ...]]:
        transform = self._simulation.current_transform(self.entity_id)
        return {
            "position": (transform.x, transform.y, transform.z),
            "rpy_deg": (
                transform.roll_deg,
                transform.pitch_deg,
                transform.yaw_deg,
            ),
        }

    def set_pose(
        self,
        position: tuple[float, float, float] | list[float],
        rpy_deg: tuple[float, float, float] | list[float] | None = None,
    ) -> None:
        runtime = self._simulation.runtime(self.entity_id)
        previous = runtime.spec.transform
        rpy = (
            (previous.roll_deg, previous.pitch_deg, previous.yaw_deg)
            if rpy_deg is None
            else rpy_deg
        )
        transform = Transform(
            x=float(position[0]),
            y=float(position[1]),
            z=float(position[2]),
            roll_deg=float(rpy[0]),
            pitch_deg=float(rpy[1]),
            yaw_deg=float(rpy[2]),
        ).validated()
        self._simulation.set_entity_transform(self.entity_id, transform)

    def set_base_velocity(
        self,
        linear: tuple[float, float, float] | list[float],
        angular: tuple[float, float, float] | list[float] = (0.0, 0.0, 0.0),
    ) -> None:
        runtime = self._simulation.runtime(self.entity_id)
        p.resetBaseVelocity(
            runtime.primary_body,
            linearVelocity=linear,
            angularVelocity=angular,
            physicsClientId=self._simulation.client_id,
        )

    def set_joint_positions(
        self,
        targets: dict[str, float],
        *,
        degrees: bool = False,
    ) -> None:
        self._simulation.set_joint_targets(
            self.entity_id,
            {
                name: math.radians(value) if degrees else float(value)
                for name, value in targets.items()
            },
        )

    def capture_camera(
        self,
        mount: str = "body",
        width: int = 320,
        height: int = 240,
    ) -> SensorFrame:
        return self._simulation.capture_camera(
            f"{self.entity_id}:{mount}", width, height
        )

    def sensor_snapshot(self) -> dict[str, Any]:
        return self._simulation.sensor_snapshot(self.entity_id)


class PyCubSim2Simulation:
    def __init__(
        self,
        config: SceneConfig | None = None,
        icub_urdf: str | Path = DEFAULT_ICUB_URDF,
    ) -> None:
        self.icub_urdf = Path(icub_urdf).resolve()
        if not self.icub_urdf.exists():
            raise FileNotFoundError(f"Official iCub URDF was not found: {self.icub_urdf}")
        self.client_id = p.connect(p.DIRECT)
        if self.client_id < 0:
            raise RuntimeError("Could not start the PyBullet physics client.")
        self.entities: dict[str, EntityRuntime] = {}
        self.floor_body_id = -1
        self.step_count = 0
        self.elapsed_s = 0.0
        self.paused = False
        self._collision_dirty = False
        self.camera_yaw = -62.0
        self.camera_pitch = -16.0
        self.camera_distance = 1.85
        self.camera_target = [-0.32, 0.0, 0.62]
        self.camera_auto_center = True
        self._initialize_world((config or default_scene()).validated())
        self.reset_camera()

    def _initialize_world(self, config: SceneConfig) -> None:
        self.config = config.validated()
        p.resetSimulation(physicsClientId=self.client_id)
        p.setGravity(
            0.0, 0.0, self.config.gravity, physicsClientId=self.client_id
        )
        p.setTimeStep(
            1.0 / self.config.physics_hz, physicsClientId=self.client_id
        )
        p.setPhysicsEngineParameter(
            fixedTimeStep=1.0 / self.config.physics_hz,
            numSolverIterations=60,
            deterministicOverlappingPairs=1,
            physicsClientId=self.client_id,
        )
        floor_half_height = 0.02
        floor_collision = p.createCollisionShape(
            p.GEOM_BOX,
            halfExtents=(100.0, 100.0, floor_half_height),
            physicsClientId=self.client_id,
        )
        floor_visual = p.createVisualShape(
            p.GEOM_BOX,
            halfExtents=(100.0, 100.0, floor_half_height),
            rgbaColor=(0.76, 0.79, 0.78, 1.0),
            physicsClientId=self.client_id,
        )
        self.floor_body_id = p.createMultiBody(
            baseMass=0.0,
            baseCollisionShapeIndex=floor_collision,
            baseVisualShapeIndex=floor_visual,
            basePosition=(0.0, 0.0, -floor_half_height),
            physicsClientId=self.client_id,
        )
        self.entities.clear()
        self.step_count = 0
        self.elapsed_s = 0.0
        for spec in self.config.entities:
            self._load_entity(spec)
        p.performCollisionDetection(physicsClientId=self.client_id)
        self._collision_dirty = False

    @staticmethod
    def _quaternion(transform: Transform, pycub: bool = False) -> tuple[float, ...]:
        yaw = transform.yaw_deg + (180.0 if pycub else 0.0)
        return p.getQuaternionFromEuler(
            (
                math.radians(transform.roll_deg),
                math.radians(transform.pitch_deg),
                math.radians(yaw),
            )
        )

    @staticmethod
    def _position(transform: Transform) -> tuple[float, float, float]:
        return transform.x, transform.y, transform.z

    def _load_entity(self, spec: EntitySpec) -> EntityRuntime:
        spec = spec.validated()
        if spec.entity_id in self.entities:
            raise ValueError(f"Duplicate entity ID: {spec.entity_id}")
        if spec.kind == "pycub":
            runtime = self._load_pycub(spec)
        elif spec.kind == "table":
            runtime = self._load_table(spec)
        elif spec.kind == "primitive":
            runtime = self._load_primitive(spec)
        elif spec.kind == "model":
            runtime = self._load_model(spec)
        elif spec.kind == "agent":
            runtime = self._load_agent(spec)
        else:
            raise ValueError(f"Unsupported entity kind: {spec.kind}")
        self.entities[spec.entity_id] = runtime
        if not spec.fixed_base:
            for articulated in self.entities.values():
                if articulated.movable_joint_ids:
                    self._apply_motor_targets(articulated)
        self._collision_dirty = True
        self._sync_auto_camera_target()
        return runtime

    def _load_pycub(self, spec: EntitySpec) -> EntityRuntime:
        body_id = p.loadURDF(
            str(prepared_icub_urdf(self.icub_urdf)),
            basePosition=self._position(spec.transform),
            baseOrientation=self._quaternion(spec.transform, pycub=True),
            useFixedBase=spec.fixed_base,
            flags=p.URDF_USE_INERTIA_FROM_FILE | p.URDF_MAINTAIN_LINK_ORDER,
            globalScaling=spec.scale,
            physicsClientId=self.client_id,
        )
        runtime = self._runtime_for_body(spec, [body_id])
        self._configure_articulated_runtime(runtime, reset_pose=True)
        runtime.random_behavior = RandomBehavior(
            abs(hash(spec.entity_id)) % (2**31)
        )
        action_path = spec.metadata.get("action_path")
        if action_path:
            try:
                runtime.keyframe_action = KeyframeAction.load(action_path)
            except (OSError, ValueError):
                runtime.keyframe_action = None
        runtime.behavior_running = spec.behavior != "Manual pose"
        self._hold_targets(runtime)
        return runtime

    def _load_table(self, spec: EntitySpec) -> EntityRuntime:
        width, depth, height = spec.size
        top_thickness = min(0.065, max(0.025, height * 0.10))
        top_half = (width / 2.0, depth / 2.0, top_thickness / 2.0)
        top_center_local = (0.0, 0.0, height - top_thickness / 2.0)
        ids = [
            self._box_body(
                spec,
                top_center_local,
                top_half,
                spec.color,
                mass=0.0,
            )
        ]
        leg_height = max(0.02, height - top_thickness)
        leg_half = (
            min(0.045, width * 0.12),
            min(0.045, depth * 0.12),
            leg_height / 2.0,
        )
        inset_x = max(0.0, width / 2.0 - leg_half[0] * 1.8)
        inset_y = max(0.0, depth / 2.0 - leg_half[1] * 1.8)
        leg_color = (
            spec.color[0] * 0.68,
            spec.color[1] * 0.68,
            spec.color[2] * 0.68,
            spec.color[3],
        )
        for dx in (-inset_x, inset_x):
            for dy in (-inset_y, inset_y):
                ids.append(
                    self._box_body(
                        spec,
                        (dx, dy, leg_height / 2.0),
                        leg_half,
                        leg_color,
                        mass=0.0,
                    )
                )
        runtime = self._runtime_for_body(spec, ids)
        self._capture_relative_body_poses(runtime)
        return runtime

    def _box_body(
        self,
        spec: EntitySpec,
        local_position: tuple[float, float, float],
        half_extents: tuple[float, float, float],
        color: tuple[float, float, float, float],
        mass: float,
    ) -> int:
        collision = p.createCollisionShape(
            p.GEOM_BOX,
            halfExtents=half_extents,
            physicsClientId=self.client_id,
        )
        visual = p.createVisualShape(
            p.GEOM_BOX,
            halfExtents=half_extents,
            rgbaColor=color,
            physicsClientId=self.client_id,
        )
        world_position, world_orientation = p.multiplyTransforms(
            self._position(spec.transform),
            self._quaternion(spec.transform),
            local_position,
            (0.0, 0.0, 0.0, 1.0),
        )
        return p.createMultiBody(
            baseMass=mass,
            baseCollisionShapeIndex=collision,
            baseVisualShapeIndex=visual,
            basePosition=world_position,
            baseOrientation=world_orientation,
            physicsClientId=self.client_id,
        )

    def _load_primitive(self, spec: EntitySpec) -> EntityRuntime:
        size_x, size_y, size_z = spec.size
        shape = spec.primitive_shape
        kwargs: dict[str, Any]
        geometry: int
        if shape == "box":
            geometry = p.GEOM_BOX
            kwargs = {"halfExtents": (size_x / 2.0, size_y / 2.0, size_z / 2.0)}
        elif shape == "sphere":
            geometry = p.GEOM_SPHERE
            kwargs = {"radius": size_x / 2.0}
        elif shape == "cylinder":
            geometry = p.GEOM_CYLINDER
            kwargs = {"radius": size_x / 2.0, "height": size_z}
        else:
            raise ValueError(f"Unsupported primitive: {shape}")
        collision = p.createCollisionShape(
            geometry, physicsClientId=self.client_id, **kwargs
        )
        visual = p.createVisualShape(
            geometry,
            rgbaColor=spec.color,
            physicsClientId=self.client_id,
            **kwargs,
        )
        body_id = p.createMultiBody(
            baseMass=0.0 if spec.fixed_base else max(0.001, spec.mass),
            baseCollisionShapeIndex=collision,
            baseVisualShapeIndex=visual,
            basePosition=self._position(spec.transform),
            baseOrientation=self._quaternion(spec.transform),
            physicsClientId=self.client_id,
        )
        p.changeDynamics(
            body_id,
            -1,
            lateralFriction=0.8,
            restitution=0.08,
            physicsClientId=self.client_id,
        )
        return self._runtime_for_body(spec, [body_id])

    def _load_model(self, spec: EntitySpec) -> EntityRuntime:
        path = validate_model_path(spec.model_path)
        suffix = path.suffix.lower()
        orientation = self._quaternion(spec.transform)
        position = self._position(spec.transform)
        if suffix == ".urdf":
            body_ids = [
                p.loadURDF(
                    str(path),
                    basePosition=position,
                    baseOrientation=orientation,
                    useFixedBase=spec.fixed_base,
                    globalScaling=spec.scale,
                    flags=p.URDF_USE_INERTIA_FROM_FILE,
                    physicsClientId=self.client_id,
                )
            ]
        elif suffix == ".sdf":
            try:
                body_ids = list(
                    p.loadSDF(
                        str(path),
                        globalScaling=spec.scale,
                        physicsClientId=self.client_id,
                    )
                )
            except TypeError:
                body_ids = list(p.loadSDF(str(path), physicsClientId=self.client_id))
            self._place_loaded_group(body_ids, spec.transform)
        elif suffix == ".xml":
            body_ids = list(p.loadMJCF(str(path), physicsClientId=self.client_id))
            self._place_loaded_group(body_ids, spec.transform)
        else:
            mesh_scale = (spec.scale, spec.scale, spec.scale)
            collision = p.createCollisionShape(
                p.GEOM_MESH,
                fileName=str(path),
                meshScale=mesh_scale,
                flags=p.GEOM_FORCE_CONCAVE_TRIMESH if spec.fixed_base else 0,
                physicsClientId=self.client_id,
            )
            visual = p.createVisualShape(
                p.GEOM_MESH,
                fileName=str(path),
                meshScale=mesh_scale,
                rgbaColor=spec.color,
                physicsClientId=self.client_id,
            )
            body_ids = [
                p.createMultiBody(
                    baseMass=0.0 if spec.fixed_base else max(0.001, spec.mass),
                    baseCollisionShapeIndex=collision,
                    baseVisualShapeIndex=visual,
                    basePosition=position,
                    baseOrientation=orientation,
                    physicsClientId=self.client_id,
                )
            ]
        if not body_ids:
            raise RuntimeError(f"Model did not create any bodies: {path}")
        if spec.fixed_base and suffix in {".sdf", ".xml"}:
            for body_id in body_ids:
                p.changeDynamics(
                    body_id, -1, mass=0.0, physicsClientId=self.client_id
                )
        runtime = self._runtime_for_body(spec, body_ids)
        self._capture_relative_body_poses(runtime)
        self._configure_articulated_runtime(runtime, reset_pose=False)
        return runtime

    def _load_agent(self, spec: EntitySpec) -> EntityRuntime:
        manifest = AgentManifest.load(spec.manifest_path)
        agent_spec = copy.deepcopy(spec)
        agent_spec.model_path = str(manifest.model_path)
        agent_spec.fixed_base = spec.fixed_base
        agent_spec.scale = spec.scale
        agent_spec.kind = "model"
        runtime = self._load_model(agent_spec)
        runtime.spec = spec
        runtime.manifest = manifest
        runtime.controller_host = ControllerHost(load_controller(manifest))
        runtime.controller_api = AgentAPI(self, spec.entity_id)
        return runtime

    def _runtime_for_body(
        self, spec: EntitySpec, body_ids: list[int]
    ) -> EntityRuntime:
        primary = body_ids[0]
        dynamics = p.getDynamicsInfo(
            primary, -1, physicsClientId=self.client_id
        )
        return EntityRuntime(
            spec=copy.deepcopy(spec),
            body_ids=list(body_ids),
            primary_body=primary,
            base_inertial_position=tuple(float(value) for value in dynamics[3]),
            base_inertial_orientation=tuple(float(value) for value in dynamics[4]),
        )

    def _capture_relative_body_poses(self, runtime: EntityRuntime) -> None:
        root_position = self._position(runtime.spec.transform)
        root_orientation = self._quaternion(
            runtime.spec.transform,
            pycub=runtime.spec.kind == "pycub",
        )
        inverse_position, inverse_orientation = p.invertTransform(
            root_position, root_orientation
        )
        runtime.relative_body_poses = {}
        for body_id in runtime.body_ids:
            position, orientation = p.getBasePositionAndOrientation(
                body_id, physicsClientId=self.client_id
            )
            relative = p.multiplyTransforms(
                inverse_position,
                inverse_orientation,
                position,
                orientation,
            )
            runtime.relative_body_poses[body_id] = (
                tuple(relative[0]),
                tuple(relative[1]),
            )

    def _place_loaded_group(
        self, body_ids: list[int], transform: Transform
    ) -> None:
        if not body_ids:
            return
        first_position, first_orientation = p.getBasePositionAndOrientation(
            body_ids[0], physicsClientId=self.client_id
        )
        inverse_position, inverse_orientation = p.invertTransform(
            first_position, first_orientation
        )
        target_position = self._position(transform)
        target_orientation = self._quaternion(transform)
        for body_id in body_ids:
            position, orientation = p.getBasePositionAndOrientation(
                body_id, physicsClientId=self.client_id
            )
            relative_position, relative_orientation = p.multiplyTransforms(
                inverse_position,
                inverse_orientation,
                position,
                orientation,
            )
            placed_position, placed_orientation = p.multiplyTransforms(
                target_position,
                target_orientation,
                relative_position,
                relative_orientation,
            )
            p.resetBasePositionAndOrientation(
                body_id,
                placed_position,
                placed_orientation,
                physicsClientId=self.client_id,
            )

    def _configure_articulated_runtime(
        self, runtime: EntityRuntime, reset_pose: bool
    ) -> None:
        body_id = runtime.primary_body
        for joint_id in range(
            p.getNumJoints(body_id, physicsClientId=self.client_id)
        ):
            info = p.getJointInfo(
                body_id, joint_id, physicsClientId=self.client_id
            )
            name = info[1].decode("utf-8")
            link_name = info[12].decode("utf-8")
            runtime.joints[name] = joint_id
            runtime.links[link_name] = joint_id
            if info[2] == p.JOINT_FIXED:
                continue
            runtime.movable_joint_ids.append(joint_id)
            if info[3] >= 0:
                runtime.q_index_joint_ids.append(joint_id)
            lower, upper = float(info[8]), float(info[9])
            if lower > upper:
                lower, upper = -math.pi, math.pi
            runtime.joint_limits[joint_id] = (lower, upper)
            target = (
                math.radians(DEFAULT_POSE_DEG.get(name, 0.0))
                if reset_pose
                else float(
                    p.getJointState(
                        body_id, joint_id, physicsClientId=self.client_id
                    )[0]
                )
            )
            target = float(np.clip(target, lower, upper))
            runtime.target_positions[joint_id] = target
            if reset_pose:
                p.resetJointState(
                    body_id,
                    joint_id,
                    target,
                    physicsClientId=self.client_id,
                )
        runtime.q_index_joint_ids.sort(
            key=lambda joint_id: p.getJointInfo(
                body_id, joint_id, physicsClientId=self.client_id
            )[3]
        )

    def _hold_targets(self, runtime: EntityRuntime) -> None:
        if not runtime.movable_joint_ids:
            return
        self._apply_motor_targets(runtime)

    def _apply_motor_targets(self, runtime: EntityRuntime) -> None:
        joint_ids = runtime.movable_joint_ids
        if not joint_ids:
            return
        positions = [
            (
                runtime.target_positions[joint_id]
                if joint_id in runtime.target_positions
                else
                p.getJointState(
                    runtime.primary_body,
                    joint_id,
                    physicsClientId=self.client_id,
                )[0]
            )
            for joint_id in joint_ids
        ]
        if not self._has_dynamic_entities():
            for joint_id, position in zip(joint_ids, positions):
                previous = runtime.applied_positions.get(joint_id)
                if previous is not None and abs(previous - position) < 1e-7:
                    continue
                p.resetJointState(
                    runtime.primary_body,
                    joint_id,
                    position,
                    targetVelocity=0.0,
                    physicsClientId=self.client_id,
                )
                runtime.applied_positions[joint_id] = position
            runtime.motor_settle_steps = 0
            self._collision_dirty = True
            return
        runtime.applied_positions.clear()
        if len(runtime.motor_forces) != len(joint_ids):
            names_by_id = {
                joint_id: name for name, joint_id in runtime.joints.items()
            }
            runtime.motor_forces.clear()
            runtime.motor_position_gains.clear()
            for joint_id in joint_ids:
                name = names_by_id.get(joint_id, "")
                if "_hand_" in name:
                    runtime.motor_forces.append(3.0)
                    runtime.motor_position_gains.append(0.18)
                elif name.startswith(
                    (
                        "l_hip",
                        "r_hip",
                        "l_knee",
                        "r_knee",
                        "l_ankle",
                        "r_ankle",
                        "torso_",
                    )
                ):
                    runtime.motor_forces.append(70.0)
                    runtime.motor_position_gains.append(0.22)
                else:
                    runtime.motor_forces.append(42.0)
                    runtime.motor_position_gains.append(0.16)
        gain_scale = max(0.35, min(2.0, runtime.behavior_speed))
        p.setJointMotorControlArray(
            runtime.primary_body,
            joint_ids,
            p.POSITION_CONTROL,
            targetPositions=positions,
            targetVelocities=[0.0] * len(joint_ids),
            forces=runtime.motor_forces,
            positionGains=[
                min(0.55, gain * gain_scale)
                for gain in runtime.motor_position_gains
            ],
            velocityGains=[1.0] * len(joint_ids),
            physicsClientId=self.client_id,
        )
        runtime.motor_settle_steps = max(
            runtime.motor_settle_steps,
            max(1, round(self.config.physics_hz * 0.5)),
        )

    def _has_dynamic_entities(self) -> bool:
        return any(
            not runtime.spec.fixed_base for runtime in self.entities.values()
        )

    def runtime(self, entity_id: str) -> EntityRuntime:
        try:
            return self.entities[entity_id]
        except KeyError as exc:
            raise KeyError(f"Unknown entity: {entity_id}") from exc

    def entity_specs(self) -> list[EntitySpec]:
        for entity_id, runtime in self.entities.items():
            if not runtime.spec.fixed_base:
                self.current_transform(entity_id, update_spec=True)
        return [copy.deepcopy(runtime.spec) for runtime in self.entities.values()]

    def current_transform(
        self, entity_id: str, *, update_spec: bool = False
    ) -> Transform:
        runtime = self.runtime(entity_id)
        position, orientation = p.getBasePositionAndOrientation(
            runtime.primary_body, physicsClientId=self.client_id
        )
        if runtime.primary_body in runtime.relative_body_poses:
            relative_position, relative_orientation = runtime.relative_body_poses[
                runtime.primary_body
            ]
        else:
            relative_position = runtime.base_inertial_position
            relative_orientation = runtime.base_inertial_orientation
        inverse_position, inverse_orientation = p.invertTransform(
            relative_position, relative_orientation
        )
        root_position, root_orientation = p.multiplyTransforms(
            position,
            orientation,
            inverse_position,
            inverse_orientation,
        )
        roll, pitch, yaw = p.getEulerFromQuaternion(root_orientation)
        yaw_deg = math.degrees(yaw)
        if runtime.spec.kind == "pycub":
            yaw_deg -= 180.0
        transform = Transform(
            x=float(root_position[0]),
            y=float(root_position[1]),
            z=float(root_position[2]),
            roll_deg=math.degrees(roll),
            pitch_deg=math.degrees(pitch),
            yaw_deg=yaw_deg,
        ).validated()
        if update_spec:
            runtime.spec.transform = transform
        return transform

    def scene_config(self) -> SceneConfig:
        return SceneConfig(
            entities=self.entity_specs(),
            gravity=self.config.gravity,
            physics_hz=self.config.physics_hz,
            control_hz=self.config.control_hz,
        ).validated()

    def save_scene(self, path: str | Path) -> None:
        self.scene_config().save(path)

    def load_scene(self, config_or_path: SceneConfig | str | Path) -> None:
        config = (
            config_or_path
            if isinstance(config_or_path, SceneConfig)
            else SceneConfig.load(config_or_path)
        )
        self.stop_all_controllers()
        self._initialize_world(config)
        self.reset_camera()

    def reset_default_scene(self) -> None:
        self.load_scene(default_scene())

    def unique_name(self, base: str) -> str:
        names = {runtime.spec.name for runtime in self.entities.values()}
        if base not in names:
            return base
        index = 2
        while f"{base} {index}" in names:
            index += 1
        return f"{base} {index}"

    def add_pycub(self) -> str:
        table = next(
            (
                runtime.spec
                for runtime in self.entities.values()
                if runtime.spec.kind == "table"
            ),
            None,
        )
        count = sum(
            runtime.spec.kind == "pycub" for runtime in self.entities.values()
        )
        center_x = table.transform.x if table else -0.5
        center_y = table.transform.y if table else 0.0
        angle = (count * 137.5) % 360.0
        radians = math.radians(angle)
        x = center_x + math.cos(radians) * 1.05
        y = center_y + math.sin(radians) * 1.05
        yaw = math.degrees(math.atan2(center_y - y, center_x - x))
        name = self.unique_name("PyCub")
        spec = EntitySpec(
            entity_id=new_entity_id("pycub"),
            name=name,
            kind="pycub",
            transform=Transform(x=x, y=y, z=0.65, yaw_deg=yaw),
            fixed_base=True,
            behavior="Manual pose",
        )
        self._load_entity(spec)
        return spec.entity_id

    def add_primitive(
        self,
        *,
        name: str,
        shape: str,
        size: tuple[float, float, float],
        mass: float,
        color: tuple[float, float, float, float],
        fixed_base: bool,
        transform: Transform | None = None,
    ) -> str:
        if transform is None:
            table = next(
                (
                    runtime.spec
                    for runtime in self.entities.values()
                    if runtime.spec.kind == "table"
                ),
                None,
            )
            if table is None:
                transform = Transform(z=size[2] / 2.0 + 0.01)
            else:
                transform = Transform(
                    x=table.transform.x,
                    y=table.transform.y,
                    z=table.transform.z + table.size[2] + size[2] / 2.0 + 0.01,
                )
        spec = EntitySpec(
            entity_id=new_entity_id("object"),
            name=self.unique_name(name),
            kind="primitive",
            transform=transform,
            fixed_base=fixed_base,
            primitive_shape=shape,
            size=size,
            mass=mass,
            color=color,
            sensors=SensorOptions(
                camera_mount="body",
                rgb=False,
                depth=False,
                segmentation=False,
                joints=False,
                imu=True,
                contact=True,
                lidar=False,
            ),
        ).validated()
        self._load_entity(spec)
        return spec.entity_id

    def add_table(
        self,
        *,
        name: str = "Table",
        size: tuple[float, float, float] = (0.72, 1.05, 0.525),
        color: tuple[float, float, float, float] = (0.68, 0.40, 0.18, 1.0),
        transform: Transform | None = None,
    ) -> str:
        count = sum(
            runtime.spec.kind == "table" for runtime in self.entities.values()
        )
        spec = EntitySpec(
            entity_id=new_entity_id("table"),
            name=self.unique_name(name),
            kind="table",
            transform=transform or Transform(x=-0.55, y=(count + 1) * 1.25),
            fixed_base=True,
            size=size,
            mass=0.0,
            color=color,
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
        ).validated()
        self._load_entity(spec)
        return spec.entity_id

    def import_model(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        fixed_base: bool = True,
        scale: float = 1.0,
        mass: float = 1.0,
        transform: Transform | None = None,
    ) -> str:
        model_path = validate_model_path(path)
        spec = EntitySpec(
            entity_id=new_entity_id("model"),
            name=self.unique_name(name or model_path.stem),
            kind="model",
            transform=transform or Transform(z=0.05),
            fixed_base=fixed_base,
            scale=scale,
            model_path=str(model_path),
            mass=mass,
            color=(0.66, 0.69, 0.72, 1.0),
            sensors=SensorOptions(
                camera_mount="body",
                rgb=True,
                depth=True,
                segmentation=False,
                joints=True,
                imu=True,
                contact=True,
                lidar=False,
            ),
        ).validated()
        self._load_entity(spec)
        return spec.entity_id

    def import_agent(
        self,
        manifest_path: str | Path,
        transform: Transform | None = None,
    ) -> str:
        manifest = AgentManifest.load(manifest_path)
        spec = EntitySpec(
            entity_id=new_entity_id("agent"),
            name=self.unique_name(manifest.name),
            kind="agent",
            transform=transform
            or Transform(
                x=manifest.spawn_position[0],
                y=manifest.spawn_position[1],
                z=manifest.spawn_position[2],
                roll_deg=manifest.spawn_rpy_deg[0],
                pitch_deg=manifest.spawn_rpy_deg[1],
                yaw_deg=manifest.spawn_rpy_deg[2],
            ),
            fixed_base=manifest.fixed_base,
            scale=manifest.scale,
            model_path=str(manifest.model_path),
            manifest_path=str(manifest.path),
            behavior="External controller",
            sensors=SensorOptions(
                camera_mount=manifest.cameras[0].name if manifest.cameras else "body",
                rgb=True,
                depth=True,
                segmentation=False,
                joints=True,
                imu=True,
                contact=True,
                lidar=False,
            ),
        ).validated()
        self._load_entity(spec)
        return spec.entity_id

    def duplicate_entity(self, entity_id: str) -> str:
        source = copy.deepcopy(self.runtime(entity_id).spec)
        source.entity_id = new_entity_id(source.kind)
        source.name = self.unique_name(source.name)
        source.transform.x += 0.25
        source.transform.y += 0.18
        self._load_entity(source)
        return source.entity_id

    def remove_entity(self, entity_id: str) -> None:
        runtime = self.runtime(entity_id)
        self.stop_controller(entity_id)
        for body_id in runtime.body_ids:
            try:
                p.removeBody(body_id, physicsClientId=self.client_id)
            except p.error:
                pass
        del self.entities[entity_id]
        self._collision_dirty = True
        self._sync_auto_camera_target()

    def update_entity(self, spec: EntitySpec) -> None:
        spec = spec.validated()
        previous = self.runtime(spec.entity_id)
        rebuild_fields = (
            previous.spec.kind != spec.kind
            or previous.spec.fixed_base != spec.fixed_base
            or previous.spec.scale != spec.scale
            or previous.spec.model_path != spec.model_path
            or previous.spec.manifest_path != spec.manifest_path
            or previous.spec.primitive_shape != spec.primitive_shape
            or previous.spec.size != spec.size
            or previous.spec.mass != spec.mass
            or previous.spec.color != spec.color
        )
        if rebuild_fields:
            self.remove_entity(spec.entity_id)
            self._load_entity(spec)
            return
        previous.spec.name = spec.name
        previous.spec.behavior = spec.behavior
        previous.spec.sensors = copy.deepcopy(spec.sensors)
        previous.spec.metadata = dict(spec.metadata)
        self.set_entity_transform(spec.entity_id, spec.transform)

    def set_entity_transform(self, entity_id: str, transform: Transform) -> None:
        runtime = self.runtime(entity_id)
        transform = transform.validated()
        runtime.spec.transform = transform
        root_position = self._position(transform)
        root_orientation = self._quaternion(
            transform, pycub=runtime.spec.kind == "pycub"
        )
        if runtime.relative_body_poses and len(runtime.body_ids) > 1:
            for body_id, (relative_position, relative_orientation) in runtime.relative_body_poses.items():
                position, orientation = p.multiplyTransforms(
                    root_position,
                    root_orientation,
                    relative_position,
                    relative_orientation,
                )
                p.resetBasePositionAndOrientation(
                    body_id,
                    position,
                    orientation,
                    physicsClientId=self.client_id,
                )
            self._collision_dirty = True
            self._sync_auto_camera_target()
            return
        com_position, com_orientation = p.multiplyTransforms(
            root_position,
            root_orientation,
            runtime.base_inertial_position,
            runtime.base_inertial_orientation,
        )
        p.resetBasePositionAndOrientation(
            runtime.primary_body,
            com_position,
            com_orientation,
            physicsClientId=self.client_id,
        )
        self._collision_dirty = True
        self._sync_auto_camera_target()

    def set_behavior(
        self,
        entity_id: str,
        behavior: str,
        *,
        running: bool = True,
        speed: float | None = None,
        intensity: float | None = None,
    ) -> None:
        runtime = self.runtime(entity_id)
        if runtime.spec.kind != "pycub":
            raise ValueError("Built-in behaviors are available for PyCub entities.")
        if behavior not in BUILTIN_BEHAVIORS:
            raise ValueError(f"Unknown behavior: {behavior}")
        if behavior == "Keyframe action" and runtime.keyframe_action is None:
            raise ValueError("Load a keyframe action before selecting it.")
        runtime.spec.behavior = behavior
        runtime.behavior_running = bool(running) and behavior != "Manual pose"
        runtime.behavior_elapsed_s = 0.0
        if speed is not None:
            runtime.behavior_speed = float(np.clip(speed, 0.05, 3.0))
        if intensity is not None:
            runtime.behavior_intensity = float(np.clip(intensity, 0.0, 1.0))
        if runtime.random_behavior is not None:
            runtime.random_behavior.reset()

    def stop_behavior(self, entity_id: str) -> None:
        runtime = self.runtime(entity_id)
        runtime.behavior_running = False

    def set_manual_joint_deg(
        self, entity_id: str, name: str, value_deg: float
    ) -> None:
        runtime = self.runtime(entity_id)
        if name not in runtime.joints:
            raise KeyError(f"Joint {name!r} is not available on {runtime.spec.name}.")
        joint_id = runtime.joints[name]
        lower, upper = runtime.joint_limits[joint_id]
        value = float(np.clip(math.radians(value_deg), lower, upper))
        runtime.manual_deg[name] = math.degrees(value)
        runtime.target_positions[joint_id] = value
        runtime.spec.behavior = "Manual pose"
        runtime.behavior_running = False
        self._apply_motor_targets(runtime)

    def set_joint_targets(
        self, entity_id: str, targets_rad: dict[str, float]
    ) -> None:
        runtime = self.runtime(entity_id)
        self._store_joint_targets(runtime, targets_rad)
        self._apply_motor_targets(runtime)

    @staticmethod
    def _store_joint_targets(
        runtime: EntityRuntime, targets_rad: dict[str, float]
    ) -> None:
        for name, value in targets_rad.items():
            joint_id = runtime.joints.get(name)
            if joint_id is None or joint_id not in runtime.joint_limits:
                continue
            runtime.target_positions[joint_id] = float(
                np.clip(value, *runtime.joint_limits[joint_id])
            )

    def set_grip(self, entity_id: str, side: str, value: float) -> None:
        runtime = self.runtime(entity_id)
        value = float(np.clip(value, 0.0, 1.0))
        if side == "l":
            runtime.left_grip = value
        elif side == "r":
            runtime.right_grip = value
        else:
            raise ValueError("Grip side must be 'l' or 'r'.")
        self._apply_grip_targets(runtime)

    def _apply_grip_targets(self, runtime: EntityRuntime) -> None:
        for side, amount in (
            ("l", runtime.left_grip),
            ("r", runtime.right_grip),
        ):
            prefix = f"{side}_hand_"
            for name, joint_id in runtime.joints.items():
                if not name.startswith(prefix) or joint_id not in runtime.joint_limits:
                    continue
                lower, upper = runtime.joint_limits[joint_id]
                closed = finger_closed_value(name, lower, upper)
                runtime.target_positions[joint_id] = amount * closed

    def load_action(self, entity_id: str, path: str | Path) -> KeyframeAction:
        runtime = self.runtime(entity_id)
        if runtime.spec.kind != "pycub":
            raise ValueError("Keyframe actions can currently be loaded on PyCub.")
        action = KeyframeAction.load(path)
        runtime.keyframe_action = action
        runtime.spec.metadata["action_path"] = str(action.source_path)
        runtime.spec.behavior = "Keyframe action"
        runtime.behavior_elapsed_s = 0.0
        runtime.behavior_running = False
        return action

    def home_entity(self, entity_id: str) -> None:
        runtime = self.runtime(entity_id)
        if not runtime.movable_joint_ids:
            return
        targets = home_targets()
        for name, value in targets.items():
            joint_id = runtime.joints.get(name)
            if joint_id is None:
                continue
            runtime.target_positions[joint_id] = float(
                np.clip(value, *runtime.joint_limits[joint_id])
            )
            runtime.manual_deg[name] = math.degrees(
                runtime.target_positions[joint_id]
            )
        runtime.left_grip = 0.0
        runtime.right_grip = 0.0
        self._apply_grip_targets(runtime)
        runtime.behavior_running = False
        runtime.behavior_elapsed_s = 0.0
        self._apply_motor_targets(runtime)

    def reach(
        self,
        entity_id: str,
        side: str,
        target: tuple[float, float, float],
    ) -> float:
        runtime = self.runtime(entity_id)
        if runtime.spec.kind != "pycub":
            raise ValueError("Cartesian reach is available for PyCub entities.")
        candidates = (
            f"{side}_hand_middle_tip",
            f"{side}_hand_dh_frame",
            f"{side}_hand",
        )
        link_id = next(
            (runtime.links[name] for name in candidates if name in runtime.links),
            None,
        )
        if link_id is None:
            raise RuntimeError(f"Could not find the {side} hand end effector.")
        lower_limits = []
        upper_limits = []
        joint_ranges = []
        rest_poses = []
        for joint_id in runtime.q_index_joint_ids:
            lower, upper = runtime.joint_limits[joint_id]
            lower_limits.append(lower)
            upper_limits.append(upper)
            joint_ranges.append(max(0.001, upper - lower))
            rest_poses.append(runtime.target_positions.get(joint_id, 0.0))
        solution = p.calculateInverseKinematics(
            runtime.primary_body,
            link_id,
            targetPosition=target,
            lowerLimits=lower_limits,
            upperLimits=upper_limits,
            jointRanges=joint_ranges,
            restPoses=rest_poses,
            maxNumIterations=120,
            residualThreshold=1e-4,
            physicsClientId=self.client_id,
        )
        allowed_names = {
            "torso_pitch",
            "torso_roll",
            "torso_yaw",
            f"{side}_shoulder_pitch",
            f"{side}_shoulder_roll",
            f"{side}_shoulder_yaw",
            f"{side}_elbow",
            f"{side}_wrist_prosup",
            f"{side}_wrist_pitch",
            f"{side}_wrist_yaw",
        }
        for joint_id, value in zip(runtime.q_index_joint_ids, solution):
            name = p.getJointInfo(
                runtime.primary_body,
                joint_id,
                physicsClientId=self.client_id,
            )[1].decode("utf-8")
            if name in allowed_names:
                runtime.target_positions[joint_id] = float(
                    np.clip(value, *runtime.joint_limits[joint_id])
                )
                runtime.manual_deg[name] = math.degrees(
                    runtime.target_positions[joint_id]
                )
        runtime.spec.behavior = "Manual pose"
        runtime.behavior_running = False
        self._apply_motor_targets(runtime)
        achieved = p.getLinkState(
            runtime.primary_body,
            link_id,
            computeForwardKinematics=True,
            physicsClientId=self.client_id,
        )[4]
        return float(np.linalg.norm(np.asarray(achieved) - np.asarray(target)))

    def start_controller(self, entity_id: str) -> None:
        runtime = self.runtime(entity_id)
        if runtime.controller_host is None or runtime.controller_api is None:
            raise RuntimeError("Selected entity has no external controller.")
        runtime.controller_host.start(runtime.controller_api)

    def stop_controller(self, entity_id: str) -> None:
        runtime = self.entities.get(entity_id)
        if runtime is None:
            return
        if runtime.controller_host is not None and runtime.controller_api is not None:
            runtime.controller_host.stop(runtime.controller_api)

    def stop_all_controllers(self) -> None:
        for entity_id in list(self.entities):
            self.stop_controller(entity_id)

    def _control_update(self, dt_s: float) -> None:
        for runtime in self.entities.values():
            if runtime.spec.kind == "pycub" and runtime.behavior_running:
                runtime.behavior_elapsed_s += dt_s
                if runtime.spec.behavior == "Keyframe action":
                    action = runtime.keyframe_action
                    if action is not None:
                        targets, left_grip, right_grip, finished = action.sample(
                            runtime.behavior_elapsed_s
                        )
                        self._store_joint_targets(runtime, targets)
                        if left_grip is not None:
                            runtime.left_grip = left_grip
                        if right_grip is not None:
                            runtime.right_grip = right_grip
                        self._apply_grip_targets(runtime)
                        if finished:
                            runtime.behavior_running = False
                else:
                    targets = behavior_targets(
                        runtime.spec.behavior,
                        runtime.behavior_elapsed_s,
                        runtime.behavior_speed,
                        runtime.behavior_intensity,
                        runtime.manual_deg,
                        runtime.random_behavior
                        or RandomBehavior(abs(hash(runtime.spec.entity_id))),
                    )
                    self._store_joint_targets(runtime, targets)
                    self._apply_grip_targets(runtime)
                self._apply_motor_targets(runtime)
            host = runtime.controller_host
            api = runtime.controller_api
            if host is not None and api is not None and host.running:
                sensors = self.sensor_snapshot(runtime.spec.entity_id)
                output = host.update(api, dt_s, sensors)
                runtime.last_controller_output = output
                self._apply_controller_output(runtime, output)

    def _apply_controller_output(
        self, runtime: EntityRuntime, output: Any
    ) -> None:
        if not isinstance(output, dict):
            return
        radians = output.get("joint_positions")
        degrees = output.get("joint_positions_deg")
        if isinstance(radians, dict):
            self.set_joint_targets(runtime.spec.entity_id, radians)
        if isinstance(degrees, dict):
            self.set_joint_targets(
                runtime.spec.entity_id,
                {name: math.radians(value) for name, value in degrees.items()},
            )
        linear = output.get("base_linear_velocity")
        angular = output.get("base_angular_velocity", (0.0, 0.0, 0.0))
        if linear is not None:
            p.resetBaseVelocity(
                runtime.primary_body,
                linearVelocity=linear,
                angularVelocity=angular,
                physicsClientId=self.client_id,
            )
        position = output.get("base_position")
        if position is not None:
            rpy = output.get(
                "base_rpy_deg",
                (
                    runtime.spec.transform.roll_deg,
                    runtime.spec.transform.pitch_deg,
                    runtime.spec.transform.yaw_deg,
                ),
            )
            self.set_entity_transform(
                runtime.spec.entity_id,
                Transform(
                    x=position[0],
                    y=position[1],
                    z=position[2],
                    roll_deg=rpy[0],
                    pitch_deg=rpy[1],
                    yaw_deg=rpy[2],
                ),
            )

    def has_active_updates(self) -> bool:
        for runtime in self.entities.values():
            if not runtime.spec.fixed_base or runtime.motor_settle_steps > 0:
                return True
            if runtime.spec.kind == "pycub" and runtime.behavior_running:
                return True
            if (
                runtime.controller_host is not None
                and runtime.controller_host.running
            ):
                return True
        return False

    def requires_physics_step(self) -> bool:
        return self._has_dynamic_entities() or any(
            runtime.motor_settle_steps > 0
            for runtime in self.entities.values()
        )

    def step(self, physics_steps: int | None = None) -> None:
        if self.paused:
            return
        control_interval = max(
            1, round(self.config.physics_hz / self.config.control_hz)
        )
        count = control_interval if physics_steps is None else max(1, physics_steps)
        for _ in range(count):
            if self.step_count % control_interval == 0:
                self._control_update(1.0 / self.config.control_hz)
            if self.requires_physics_step():
                p.stepSimulation(physicsClientId=self.client_id)
                self._collision_dirty = False
                for runtime in self.entities.values():
                    runtime.motor_settle_steps = max(
                        0, runtime.motor_settle_steps - 1
                    )
            self.step_count += 1
            self.elapsed_s += 1.0 / self.config.physics_hz

    def camera_sources(self) -> list[tuple[str, str]]:
        sources = [("world", "World camera"), ("webcam:0", "Mac webcam 0")]
        for runtime in self.entities.values():
            entity_id = runtime.spec.entity_id
            name = runtime.spec.name
            if runtime.spec.kind == "pycub":
                sources.extend(
                    (
                        (f"{entity_id}:left_eye", f"{name} / Left eye"),
                        (f"{entity_id}:right_eye", f"{name} / Right eye"),
                        (f"{entity_id}:body", f"{name} / Body camera"),
                    )
                )
            elif runtime.manifest is not None and runtime.manifest.cameras:
                sources.extend(
                    (
                        f"{entity_id}:{camera.name}",
                        f"{name} / {camera.name}",
                    )
                    for camera in runtime.manifest.cameras
                )
            else:
                sources.append((f"{entity_id}:body", f"{name} / Body camera"))
        return sources

    @staticmethod
    def _rotation_matrix(
        quaternion: tuple[float, float, float, float]
    ) -> np.ndarray:
        return np.asarray(
            p.getMatrixFromQuaternion(quaternion), dtype=np.float64
        ).reshape(3, 3)

    def _camera_definition(
        self, runtime: EntityRuntime, mount: str
    ) -> tuple[int, CameraDefinition]:
        if runtime.spec.kind == "pycub" and mount in {"left_eye", "right_eye"}:
            prefix = "l" if mount == "left_eye" else "r"
            link_name = f"{prefix}_eye_pupil"
            return (
                runtime.links.get(link_name, runtime.links.get("head", -1)),
                CameraDefinition(
                    name=mount,
                    link=link_name,
                    offset=(0.0, 0.0, 0.04),
                    forward=(0.0, 0.0, 1.0),
                    up=(0.0, -1.0, 0.0),
                    fov_deg=70.0,
                ),
            )
        if runtime.manifest is not None:
            for camera in runtime.manifest.cameras:
                if camera.name == mount:
                    return runtime.links.get(camera.link, -1), camera
        return (
            -1,
            CameraDefinition(
                name="body",
                offset=(0.0, 0.0, 0.42),
                forward=(1.0, 0.0, 0.0),
                up=(0.0, 0.0, 1.0),
                fov_deg=70.0,
            ),
        )

    def camera_pose(
        self, source: str
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        if ":" not in source or source.startswith(("world", "webcam")):
            raise ValueError(f"Source does not provide a simulated camera pose: {source}")
        entity_id, mount = source.split(":", 1)
        runtime = self.runtime(entity_id)
        link_id, definition = self._camera_definition(runtime, mount)
        if link_id >= 0:
            state = p.getLinkState(
                runtime.primary_body,
                link_id,
                computeForwardKinematics=True,
                physicsClientId=self.client_id,
            )
            center = np.asarray(state[4], dtype=np.float64)
            rotation = self._rotation_matrix(state[5])
        else:
            position, orientation = p.getBasePositionAndOrientation(
                runtime.primary_body, physicsClientId=self.client_id
            )
            center = np.asarray(position, dtype=np.float64)
            rotation = self._rotation_matrix(orientation)
        offset = np.asarray(definition.offset, dtype=np.float64)
        forward = np.asarray(definition.forward, dtype=np.float64)
        up = np.asarray(definition.up, dtype=np.float64)
        eye = center + rotation @ offset
        direction = rotation @ forward
        up_world = rotation @ up
        direction /= max(1e-9, float(np.linalg.norm(direction)))
        up_world /= max(1e-9, float(np.linalg.norm(up_world)))
        return eye, eye + direction, up_world, definition.fov_deg

    def capture_camera(
        self, source: str, width: int = 480, height: int = 320
    ) -> SensorFrame:
        width = max(32, int(width))
        height = max(32, int(height))
        eye, target, up, fov = self.camera_pose(source)
        near, far = 0.02, 10.0
        view_matrix = p.computeViewMatrix(eye, target, up)
        projection = p.computeProjectionMatrixFOV(
            fov=fov,
            aspect=width / height,
            nearVal=near,
            farVal=far,
        )
        _, _, rgba, depth, segmentation = p.getCameraImage(
            width,
            height,
            viewMatrix=view_matrix,
            projectionMatrix=projection,
            renderer=p.ER_TINY_RENDERER,
            shadow=0,
            flags=p.ER_SEGMENTATION_MASK_OBJECT_AND_LINKINDEX,
            physicsClientId=self.client_id,
        )
        rgb = np.asarray(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3]
        depth_buffer = np.asarray(depth, dtype=np.float32).reshape(height, width)
        depth_m = far * near / (far - (far - near) * depth_buffer)
        segmentation_array = np.asarray(segmentation, dtype=np.int32).reshape(
            height, width
        )
        return SensorFrame(
            rgb=rgb,
            depth_m=depth_m,
            depth_rgb=depth_colormap(depth_m, near, far),
            segmentation=segmentation_array,
            segmentation_rgb=segmentation_colormap(segmentation_array),
            source=source,
        )

    def sensor_snapshot(self, entity_id: str) -> dict[str, Any]:
        runtime = self.runtime(entity_id)
        options = runtime.spec.sensors
        snapshot: dict[str, Any] = {
            "entity_id": entity_id,
            "time_s": self.elapsed_s,
        }
        if options.joints and runtime.movable_joint_ids:
            snapshot["joints"] = {
                p.getJointInfo(
                    runtime.primary_body,
                    joint_id,
                    physicsClientId=self.client_id,
                )[1].decode("utf-8"): {
                    "position": float(state[0]),
                    "velocity": float(state[1]),
                    "torque": float(state[3]),
                }
                for joint_id in runtime.movable_joint_ids
                for state in (
                    p.getJointState(
                        runtime.primary_body,
                        joint_id,
                        physicsClientId=self.client_id,
                    ),
                )
            }
        if options.imu:
            position, orientation = p.getBasePositionAndOrientation(
                runtime.primary_body, physicsClientId=self.client_id
            )
            linear, angular = p.getBaseVelocity(
                runtime.primary_body, physicsClientId=self.client_id
            )
            snapshot["imu"] = {
                "position": tuple(float(value) for value in position),
                "rpy_deg": tuple(
                    math.degrees(value)
                    for value in p.getEulerFromQuaternion(orientation)
                ),
                "linear_velocity": tuple(float(value) for value in linear),
                "angular_velocity": tuple(float(value) for value in angular),
            }
        if options.contact:
            if self._collision_dirty:
                p.performCollisionDetection(physicsClientId=self.client_id)
                self._collision_dirty = False
            contacts = p.getContactPoints(
                bodyA=runtime.primary_body,
                physicsClientId=self.client_id,
            )
            snapshot["contact"] = {
                "count": len(contacts),
                "max_force": max(
                    (float(contact[9]) for contact in contacts), default=0.0
                ),
                "body_ids": sorted(
                    {
                        int(contact[2])
                        for contact in contacts
                        if int(contact[2]) >= 0
                    }
                ),
            }
        if options.lidar:
            snapshot["lidar_m"] = self.read_lidar(entity_id)
        return snapshot

    def read_lidar(
        self,
        entity_id: str,
        ray_count: int = 24,
        max_distance: float = 3.0,
    ) -> list[float]:
        runtime = self.runtime(entity_id)
        base_position, base_orientation = p.getBasePositionAndOrientation(
            runtime.primary_body,
            physicsClientId=self.client_id,
        )
        origin = np.asarray(base_position, dtype=np.float64)
        origin[2] += 0.38
        yaw = p.getEulerFromQuaternion(base_orientation)[2]
        angles = yaw + np.linspace(-math.pi, math.pi, ray_count, endpoint=False)
        starts = [origin.tolist()] * ray_count
        ends = [
            (
                origin
                + np.asarray(
                    (math.cos(angle), math.sin(angle), 0.0), dtype=np.float64
                )
                * max_distance
            ).tolist()
            for angle in angles
        ]
        results = p.rayTestBatch(
            starts, ends, physicsClientId=self.client_id
        )
        return [
            max_distance if result[0] < 0 else float(result[2]) * max_distance
            for result in results
        ]

    def entity_bounds(
        self, entity_id: str
    ) -> tuple[np.ndarray, np.ndarray]:
        runtime = self.runtime(entity_id)
        lower = np.full(3, np.inf, dtype=np.float64)
        upper = np.full(3, -np.inf, dtype=np.float64)
        for body_id in runtime.body_ids:
            link_ids = range(
                -1,
                p.getNumJoints(body_id, physicsClientId=self.client_id),
            )
            for link_id in link_ids:
                try:
                    link_lower, link_upper = p.getAABB(
                        body_id,
                        link_id,
                        physicsClientId=self.client_id,
                    )
                except p.error:
                    continue
                lower = np.minimum(lower, np.asarray(link_lower, dtype=np.float64))
                upper = np.maximum(upper, np.asarray(link_upper, dtype=np.float64))
        if not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper)):
            transform = runtime.spec.transform
            center = np.asarray(
                (transform.x, transform.y, transform.z), dtype=np.float64
            )
            lower = center - 0.1
            upper = center + 0.1
        return lower, upper

    def scene_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.entities:
            return (
                np.asarray((-0.75, -0.75, 0.0), dtype=np.float64),
                np.asarray((0.75, 0.75, 1.0), dtype=np.float64),
            )
        bounds = [
            self.entity_bounds(entity_id) for entity_id in self.entities
        ]
        lower = np.min(np.stack([item[0] for item in bounds]), axis=0)
        upper = np.max(np.stack([item[1] for item in bounds]), axis=0)
        return lower, upper

    def scene_center(self) -> tuple[float, float, float]:
        lower, upper = self.scene_bounds()
        center = (lower + upper) / 2.0
        center[2] = max(0.2, center[2])
        return tuple(float(value) for value in center)

    def _sync_auto_camera_target(self) -> None:
        if not getattr(self, "camera_auto_center", False):
            return
        self.camera_target = list(self.scene_center())

    def fit_camera_to_scene(self, aspect: float = 1.5) -> None:
        lower, upper = self.scene_bounds()
        self.camera_target = list(self.scene_center())
        aspect = float(np.clip(aspect, 0.35, 4.0))
        corners = [
            np.asarray((x, y, z, 1.0), dtype=np.float64)
            for x in (lower[0], upper[0])
            for y in (lower[1], upper[1])
            for z in (lower[2], upper[2])
        ]
        projection = np.asarray(
            p.computeProjectionMatrixFOV(
                fov=54.0,
                aspect=aspect,
                nearVal=0.03,
                farVal=40.0,
            ),
            dtype=np.float64,
        ).reshape(4, 4, order="F")

        def fits(distance: float) -> bool:
            view = np.asarray(
                p.computeViewMatrixFromYawPitchRoll(
                    cameraTargetPosition=tuple(self.camera_target),
                    distance=distance,
                    yaw=self.camera_yaw,
                    pitch=self.camera_pitch,
                    roll=0.0,
                    upAxisIndex=2,
                ),
                dtype=np.float64,
            ).reshape(4, 4, order="F")
            transform = projection @ view
            for corner in corners:
                clip = transform @ corner
                if clip[3] <= 1e-8:
                    return False
                ndc = clip[:3] / clip[3]
                if abs(float(ndc[0])) > 0.86 or abs(float(ndc[1])) > 0.86:
                    return False
            return True

        lower_distance = 0.65
        upper_distance = 18.0
        for _ in range(32):
            middle = (lower_distance + upper_distance) / 2.0
            if fits(middle):
                upper_distance = middle
            else:
                lower_distance = middle
        self.camera_distance = float(
            np.clip(upper_distance, 0.65, 18.0)
        )
        if not fits(self.camera_distance):
            self.camera_distance = 18.0
        self.camera_auto_center = True

    def reset_camera(self) -> None:
        self.camera_yaw = -62.0
        self.camera_pitch = -16.0
        self.fit_camera_to_scene()

    def focus_entity(self, entity_id: str) -> None:
        lower, upper = self.entity_bounds(entity_id)
        self.camera_target = [
            float((lower[0] + upper[0]) / 2.0),
            float((lower[1] + upper[1]) / 2.0),
            float(max(0.2, (lower[2] + upper[2]) / 2.0)),
        ]
        self.camera_auto_center = False

    def orbit_camera(self, delta_x: float, delta_y: float) -> None:
        self.camera_yaw = (self.camera_yaw - delta_x * 0.35) % 360.0
        self.camera_pitch = float(
            np.clip(self.camera_pitch + delta_y * 0.25, -82.0, 10.0)
        )

    def zoom_camera(self, amount: float) -> None:
        self.camera_distance = float(
            np.clip(
                self.camera_distance * math.exp(-amount * 0.12),
                0.65,
                12.0,
            )
        )

    def pan_camera(self, delta_x: float, delta_y: float) -> None:
        scale = self.camera_distance * 0.0018
        yaw = math.radians(self.camera_yaw)
        right = np.asarray((math.cos(yaw), math.sin(yaw), 0.0))
        forward = np.asarray((-math.sin(yaw), math.cos(yaw), 0.0))
        shift = -delta_x * right * scale + delta_y * forward * scale
        self.camera_target[0] += float(shift[0])
        self.camera_target[1] += float(shift[1])
        self.camera_auto_center = False

    def _scene_span(self) -> float:
        lower, upper = self.scene_bounds()
        return max(
            0.8,
            float(upper[0] - lower[0]) / 2.0 + 0.35,
            float(upper[1] - lower[1]) / 2.0 + 0.35,
        )

    def camera_matrices(
        self,
        width: int,
        height: int,
        view: str = "World",
    ) -> tuple[list[float], list[float], float, float]:
        width = max(64, int(width))
        height = max(64, int(height))
        aspect = width / height
        scene_center = self.scene_center()
        if view == "Top":
            span = self._scene_span()
            fov = 50.0
            vertical_span = span if aspect >= 1.0 else span / aspect
            camera_height = (
                vertical_span / math.tan(math.radians(fov / 2.0)) * 1.08
            )
            near, far = 0.03, camera_height + 8.0
            view_matrix = p.computeViewMatrix(
                cameraEyePosition=(
                    scene_center[0],
                    scene_center[1],
                    camera_height,
                ),
                cameraTargetPosition=(
                    scene_center[0],
                    scene_center[1],
                    0.0,
                ),
                cameraUpVector=(0.0, 1.0, 0.0),
            )
            projection = p.computeProjectionMatrixFOV(
                fov=fov,
                aspect=aspect,
                nearVal=near,
                farVal=far,
            )
        elif view == "Side":
            distance = max(2.2, self._scene_span() * 1.8)
            near, far = 0.03, max(20.0, distance + 12.0)
            view_matrix = p.computeViewMatrix(
                cameraEyePosition=(
                    scene_center[0],
                    scene_center[1] - distance,
                    max(1.25, scene_center[2]),
                ),
                cameraTargetPosition=scene_center,
                cameraUpVector=(0.0, 0.0, 1.0),
            )
            projection = p.computeProjectionMatrixFOV(
                fov=48.0,
                aspect=aspect,
                nearVal=near,
                farVal=far,
            )
        else:
            near, far = 0.03, max(20.0, self.camera_distance + 14.0)
            view_matrix = p.computeViewMatrixFromYawPitchRoll(
                cameraTargetPosition=tuple(self.camera_target),
                distance=self.camera_distance,
                yaw=self.camera_yaw,
                pitch=self.camera_pitch,
                roll=0.0,
                upAxisIndex=2,
            )
            projection = p.computeProjectionMatrixFOV(
                fov=54.0,
                aspect=aspect,
                nearVal=near,
                farVal=far,
            )
        return list(view_matrix), list(projection), near, far

    def screen_ray(
        self,
        view: str,
        pixel_x: float,
        pixel_y: float,
        width: int,
        height: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        if view not in {"World", "Top", "Side"}:
            raise ValueError(f"Screen rays are unavailable for {view}.")
        view_matrix, projection, _near, _far = self.camera_matrices(
            width, height, view
        )
        view_array = np.asarray(view_matrix, dtype=np.float64).reshape(
            4, 4, order="F"
        )
        projection_array = np.asarray(
            projection, dtype=np.float64
        ).reshape(4, 4, order="F")
        inverse = np.linalg.inv(projection_array @ view_array)
        ndc_x = 2.0 * (float(pixel_x) + 0.5) / max(1, width) - 1.0
        ndc_y = 1.0 - 2.0 * (float(pixel_y) + 0.5) / max(1, height)

        points: list[np.ndarray] = []
        for ndc_z in (-1.0, 1.0):
            homogeneous = inverse @ np.asarray(
                (ndc_x, ndc_y, ndc_z, 1.0), dtype=np.float64
            )
            points.append(homogeneous[:3] / homogeneous[3])
        return points[0], points[1]

    def pick_entity(
        self,
        view: str,
        pixel_x: float,
        pixel_y: float,
        width: int,
        height: int,
    ) -> tuple[str | None, tuple[float, float, float] | None]:
        ray_from, ray_to = self.screen_ray(
            view, pixel_x, pixel_y, width, height
        )
        result = p.rayTest(
            ray_from.tolist(),
            ray_to.tolist(),
            physicsClientId=self.client_id,
        )[0]
        body_id = int(result[0])
        if body_id < 0 or body_id == self.floor_body_id:
            return None, None
        for entity_id, runtime in self.entities.items():
            if body_id in runtime.body_ids:
                return (
                    entity_id,
                    tuple(float(value) for value in result[3]),
                )
        return None, None

    def screen_to_plane(
        self,
        view: str,
        pixel_x: float,
        pixel_y: float,
        width: int,
        height: int,
        plane_z: float,
    ) -> tuple[float, float, float] | None:
        ray_from, ray_to = self.screen_ray(
            view, pixel_x, pixel_y, width, height
        )
        direction = ray_to - ray_from
        if abs(float(direction[2])) < 1e-9:
            return None
        amount = (float(plane_z) - float(ray_from[2])) / float(direction[2])
        if amount < 0.0:
            return None
        point = ray_from + direction * amount
        return tuple(float(value) for value in point)

    def entity_screen_bounds(
        self,
        entity_id: str,
        view: str,
        width: int,
        height: int,
    ) -> tuple[float, float, float, float] | None:
        if view not in {"World", "Top", "Side"}:
            return None
        lower, upper = self.entity_bounds(entity_id)
        view_matrix, projection, _near, _far = self.camera_matrices(
            width, height, view
        )
        transform = (
            np.asarray(projection, dtype=np.float64).reshape(4, 4, order="F")
            @ np.asarray(view_matrix, dtype=np.float64).reshape(
                4, 4, order="F"
            )
        )
        projected: list[tuple[float, float]] = []
        for x in (lower[0], upper[0]):
            for y in (lower[1], upper[1]):
                for z in (lower[2], upper[2]):
                    clip = transform @ np.asarray((x, y, z, 1.0))
                    if clip[3] <= 1e-9:
                        continue
                    ndc = clip[:3] / clip[3]
                    if ndc[2] < -1.0 or ndc[2] > 1.0:
                        continue
                    projected.append(
                        (
                            (float(ndc[0]) + 1.0) * width / 2.0,
                            (1.0 - float(ndc[1])) * height / 2.0,
                        )
                    )
        if not projected:
            return None
        x_values = [point[0] for point in projected]
        y_values = [point[1] for point in projected]
        return min(x_values), min(y_values), max(x_values), max(y_values)

    def render(
        self,
        width: int,
        height: int,
        view: str = "World",
        shadows: bool = True,
    ) -> np.ndarray:
        width = max(64, int(width))
        height = max(64, int(height))
        view_matrix, projection, _near, _far = self.camera_matrices(
            width, height, view
        )
        _, _, rgba, _, _ = p.getCameraImage(
            width,
            height,
            viewMatrix=view_matrix,
            projectionMatrix=projection,
            renderer=p.ER_TINY_RENDERER,
            shadow=int(shadows),
            lightDirection=(1.2, -1.0, 2.4),
            lightColor=(1.0, 0.98, 0.94),
            lightDistance=4.0,
            lightAmbientCoeff=0.42,
            lightDiffuseCoeff=0.62,
            lightSpecularCoeff=0.14,
            physicsClientId=self.client_id,
        )
        return np.asarray(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3]

    def close(self) -> None:
        self.stop_all_controllers()
        if self.client_id >= 0 and p.isConnected(self.client_id):
            p.disconnect(self.client_id)
        self.client_id = -1
