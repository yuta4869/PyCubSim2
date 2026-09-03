"""Deterministic PyBullet X/T/P/I episode acquisition."""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pybullet as p

from pycubsim2.config import Transform
from pycubsim2.simulation import PyCubSim2Simulation

SCHEMA_VERSION = 1
JOINT_NAMES = (
    "l_shoulder_pitch",
    "l_shoulder_roll",
    "l_shoulder_yaw",
    "l_elbow",
    "l_wrist_prosup",
    "l_wrist_pitch",
    "l_wrist_yaw",
)
POSTURES = {
    "extended": {"l_elbow": 25.0, "l_shoulder_roll": 25.0},
    "neutral": {"l_elbow": 58.0, "l_shoulder_roll": 32.0},
    "flexed": {"l_elbow": 95.0, "l_shoulder_roll": 45.0},
}
SPEEDS_M_S = {"slow": 0.12, "medium": 0.25, "fast": 0.50}
BODY_CONDITIONS = {
    "rigid": {"force_scale": 1.0, "position_gain_scale": 1.0},
    "compliant": {"force_scale": 0.05, "position_gain_scale": 0.10},
}
PROBE_COLORS = (
    (0.82, 0.16, 0.10, 1.0),
    (0.10, 0.45, 0.82, 1.0),
    (0.88, 0.62, 0.08, 1.0),
)


@dataclass(frozen=True)
class EpisodeConfig:
    episode_id: str
    seed: int
    speed: str = "medium"
    posture: str = "neutral"
    contact_location: str = "hand"
    body_condition: str = "rigid"
    role: str = "self"
    pair_id: str | None = None
    self_body_condition: str | None = None
    dissociation_condition: str | None = None
    no_contact: bool = False
    randomize_appearance: bool = True
    duration_s: float = 2.0
    image_width: int = 128
    image_height: int = 128
    camera_hz: int = 30
    stop_probe_at_s: float | None = None

    def validate(self) -> None:
        if self.speed not in SPEEDS_M_S:
            raise ValueError(f"Unknown speed: {self.speed}")
        if self.posture not in POSTURES:
            raise ValueError(f"Unknown posture: {self.posture}")
        if self.contact_location not in {"hand", "forearm"}:
            raise ValueError(f"Unknown contact location: {self.contact_location}")
        if self.body_condition not in BODY_CONDITIONS:
            raise ValueError(f"Unknown body condition: {self.body_condition}")
        if self.role not in {"self", "other"}:
            raise ValueError("role must be 'self' or 'other'")
        if self.self_body_condition not in {None, *BODY_CONDITIONS}:
            raise ValueError(f"Unknown Self body condition: {self.self_body_condition}")
        if self.duration_s <= 0.0:
            raise ValueError("duration_s must be positive")
        if self.stop_probe_at_s is not None and not 0.0 <= self.stop_probe_at_s < self.duration_s:
            raise ValueError("stop_probe_at_s must lie within the episode")


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def _link_position(simulation: PyCubSim2Simulation, entity_id: str, name: str) -> np.ndarray:
    runtime = simulation.runtime(entity_id)
    state = p.getLinkState(
        runtime.primary_body,
        runtime.links[name],
        computeForwardKinematics=1,
        physicsClientId=simulation.client_id,
    )
    return np.asarray(state[4], dtype=np.float64)


def _probe_target(
    t: float,
    start: np.ndarray,
    contact: np.ndarray,
    travel_sign: float,
    speed_m_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    if t < 0.4:
        return start, np.zeros(3)
    if t < 0.9:
        target = start.copy()
        target[0] += travel_sign * speed_m_s * (t - 0.4)
        return target, np.asarray((travel_sign * speed_m_s, 0.0, 0.0))
    if t < 1.1:
        return contact, np.zeros(3)
    if t < 1.4:
        fraction = (t - 1.1) / 0.3
        return (
            contact * (1.0 - fraction) + start * fraction,
            (start - contact) / 0.3,
        )
    return start, np.zeros(3)


def _joint_sample(
    simulation: PyCubSim2Simulation, entity_id: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    runtime = simulation.runtime(entity_id)
    states = p.getJointStates(
        runtime.primary_body,
        [runtime.joints[name] for name in JOINT_NAMES],
        physicsClientId=simulation.client_id,
    )
    return tuple(
        np.asarray([float(state[index]) for state in states], dtype=np.float32)
        for index in (0, 1, 3)
    )


def _contact_arrays(points: list[dict[str, Any]], limit: int = 8) -> dict[str, np.ndarray]:
    selected = sorted(points, key=lambda item: item["normal_force"], reverse=True)[:limit]
    result = {
        "body_id_a": np.full(limit, -1, dtype=np.int32),
        "body_id_b": np.full(limit, -1, dtype=np.int32),
        "link_id_a": np.full(limit, -1, dtype=np.int32),
        "link_id_b": np.full(limit, -1, dtype=np.int32),
        "position_on_a": np.zeros((limit, 3), dtype=np.float32),
        "position_on_b": np.zeros((limit, 3), dtype=np.float32),
        "normal_on_b": np.zeros((limit, 3), dtype=np.float32),
        "normal_force": np.zeros(limit, dtype=np.float32),
        "lateral_force": np.zeros((limit, 2), dtype=np.float32),
        "relative_normal_velocity": np.zeros(limit, dtype=np.float32),
    }
    for index, point in enumerate(selected):
        for name in ("body_id_a", "body_id_b", "link_id_a", "link_id_b"):
            result[name][index] = point[name]
        for name in ("position_on_a", "position_on_b", "normal_on_b"):
            result[name][index] = point[name]
        result["normal_force"][index] = point["normal_force"]
        result["lateral_force"][index] = (
            point["lateral_force_1"],
            point["lateral_force_2"],
        )
        result["relative_normal_velocity"][index] = point[
            "relative_normal_velocity"
        ]
    return result


def run_episode(config: EpisodeConfig, output_root: str | Path) -> dict[str, Any]:
    """Run and save one raw episode; return its deterministic metadata."""
    config.validate()
    rng = np.random.default_rng(config.seed)
    output_dir = Path(output_root) / config.episode_id
    output_dir.mkdir(parents=True, exist_ok=True)
    simulation = PyCubSim2Simulation()
    try:
        simulation.remove_entity("table_1")
        observer_id = "pycub_1"
        if config.role == "other":
            subject_id = simulation.add_pycub()
            simulation.set_entity_transform(
                subject_id, Transform(x=-1.0, y=0.0, z=0.65, yaw_deg=0.0)
            )
        else:
            subject_id = observer_id

        simulation.set_manual_joint_deg(
            observer_id, "neck_yaw", 25.0 if config.role == "self" else -20.0
        )

        for name, degrees in POSTURES[config.posture].items():
            simulation.set_manual_joint_deg(subject_id, name, degrees)

        link_name = "l_hand" if config.contact_location == "hand" else "l_forearm"
        target_link_position = _link_position(simulation, subject_id, link_name)
        speed_m_s = SPEEDS_M_S[config.speed] * float(rng.uniform(0.98, 1.02))
        travel_sign = 1.0 if config.role == "self" else -1.0
        contact_position = target_link_position.copy()
        contact_position[0] -= travel_sign * 0.045
        contact_position[1:] += rng.uniform(-0.004, 0.004, size=2)
        if config.no_contact:
            contact_position[1] += 0.25
        start_position = contact_position.copy()
        start_position[0] -= travel_sign * speed_m_s * 0.5

        color = (
            PROBE_COLORS[config.seed % len(PROBE_COLORS)]
            if config.randomize_appearance
            else PROBE_COLORS[0]
        )
        probe_id = simulation.add_primitive(
            name="Spherical probe",
            shape="sphere",
            size=(0.045, 0.045, 0.045),
            mass=0.12,
            color=color,
            fixed_base=False,
            transform=Transform(*start_position),
        )
        probe = simulation.runtime(probe_id)
        p.changeDynamics(
            probe.primary_body,
            -1,
            linearDamping=0.0,
            angularDamping=0.0,
            restitution=0.0,
            physicsClientId=simulation.client_id,
        )
        simulation.step(round(0.5 * simulation.config.physics_hz))
        p.resetBasePositionAndOrientation(
            probe.primary_body,
            start_position,
            (0.0, 0.0, 0.0, 1.0),
            physicsClientId=simulation.client_id,
        )
        p.resetBaseVelocity(
            probe.primary_body,
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            physicsClientId=simulation.client_id,
        )
        body = BODY_CONDITIONS[config.body_condition]
        simulation.scale_joint_motor_profile(
            subject_id,
            force_scale=body["force_scale"],
            position_gain_scale=body["position_gain_scale"],
            joint_names=JOINT_NAMES,
        )
        simulation.step_count = 0
        simulation.elapsed_s = 0.0

        physics_hz = simulation.config.physics_hz
        dt = 1.0 / physics_hz
        steps = round(config.duration_s * physics_hz)
        camera_stride = max(1, round(physics_hz / config.camera_hz))
        times: list[float] = []
        positions: list[np.ndarray] = []
        velocities: list[np.ndarray] = []
        torques: list[np.ndarray] = []
        powers: list[np.ndarray] = []
        cumulative_loads: list[float] = []
        filtered_loads: list[float] = []
        probe_positions: list[tuple[float, ...]] = []
        probe_velocities: list[tuple[float, ...]] = []
        contact_counts: list[int] = []
        contact_forces: list[float] = []
        contact_peaks: list[float] = []
        contact_impulses: list[float] = []
        contact_durations: list[float] = []
        contact_records: dict[str, list[np.ndarray]] = {}
        rgb_times: list[float] = []
        rgb_frames: list[np.ndarray] = []
        cumulative_load = 0.0
        filtered_load = 0.0
        impulse = 0.0
        duration = 0.0
        peak_force = 0.0
        stopped_position: np.ndarray | None = None

        for step in range(steps):
            t = step * dt
            current_position = np.asarray(
                p.getBasePositionAndOrientation(
                    probe.primary_body, physicsClientId=simulation.client_id
                )[0]
            )
            if config.stop_probe_at_s is not None and t >= config.stop_probe_at_s:
                if stopped_position is None:
                    stopped_position = current_position.copy()
                target, target_velocity = stopped_position, np.zeros(3)
            else:
                target, target_velocity = _probe_target(
                    t, start_position, contact_position, travel_sign, speed_m_s
                )
            current_velocity = np.asarray(
                p.getBaseVelocity(
                    probe.primary_body, physicsClientId=simulation.client_id
                )[0]
            )
            drive_force = (
                500.0 * (target - current_position)
                + 10.0 * (target_velocity - current_velocity)
                + np.asarray((0.0, 0.0, 0.12 * 9.81))
            )
            p.applyExternalForce(
                probe.primary_body,
                -1,
                np.clip(drive_force, -30.0, 30.0).tolist(),
                (0.0, 0.0, 0.0),
                p.WORLD_FRAME,
                physicsClientId=simulation.client_id,
            )
            simulation.step(1)

            position, velocity, torque = _joint_sample(simulation, subject_id)
            power = np.abs(torque * velocity)
            torque_load = float(np.abs(torque).sum())
            cumulative_load += torque_load * dt
            filtered_load += (1.0 - math.exp(-dt / 0.1)) * (
                torque_load - filtered_load
            )
            points = simulation.contact_points(subject_id, probe_id)
            force = float(sum(point["normal_force"] for point in points))
            impulse += force * dt
            duration += dt if points else 0.0
            peak_force = max(peak_force, force)
            record = _contact_arrays(points)
            for name, value in record.items():
                contact_records.setdefault(name, []).append(value)

            times.append(simulation.elapsed_s)
            positions.append(position)
            velocities.append(velocity)
            torques.append(torque)
            powers.append(power)
            cumulative_loads.append(cumulative_load)
            filtered_loads.append(filtered_load)
            probe_positions.append(
                tuple(
                    float(value)
                    for value in p.getBasePositionAndOrientation(
                        probe.primary_body, physicsClientId=simulation.client_id
                    )[0]
                )
            )
            probe_velocities.append(
                tuple(
                    float(value)
                    for value in p.getBaseVelocity(
                        probe.primary_body, physicsClientId=simulation.client_id
                    )[0]
                )
            )
            contact_counts.append(len(points))
            contact_forces.append(force)
            contact_peaks.append(peak_force)
            contact_impulses.append(impulse)
            contact_durations.append(duration)

            if step % camera_stride == 0:
                frame = simulation.capture_camera(
                    f"{observer_id}:left_eye",
                    width=config.image_width,
                    height=config.image_height,
                )
                rgb_times.append(simulation.elapsed_s)
                rgb_frames.append(frame.rgb)

        trajectory = {
            "time_s": np.asarray(times, dtype=np.float64),
            "joint_names": np.asarray(JOINT_NAMES),
            "joint_position": np.asarray(positions, dtype=np.float32),
            "joint_velocity": np.asarray(velocities, dtype=np.float32),
            "joint_torque": np.asarray(torques, dtype=np.float32),
            "mechanical_power": np.asarray(powers, dtype=np.float32),
            "cumulative_torque_load": np.asarray(cumulative_loads, dtype=np.float32),
            "filtered_torque_load": np.asarray(filtered_loads, dtype=np.float32),
            "probe_position": np.asarray(probe_positions, dtype=np.float32),
            "probe_velocity": np.asarray(probe_velocities, dtype=np.float32),
            "contact_count": np.asarray(contact_counts, dtype=np.int16),
            "contact_force": np.asarray(contact_forces, dtype=np.float32),
            "peak_contact_force": np.asarray(contact_peaks, dtype=np.float32),
            "contact_impulse": np.asarray(contact_impulses, dtype=np.float32),
            "contact_duration_s": np.asarray(contact_durations, dtype=np.float32),
            **{
                f"contact_{name}": np.asarray(values)
                for name, values in contact_records.items()
            },
        }
        np.savez_compressed(output_dir / "trajectory.npz", **trajectory)
        np.savez_compressed(
            output_dir / "rgb.npz",
            time_s=np.asarray(rgb_times, dtype=np.float64),
            rgb=np.asarray(rgb_frames, dtype=np.uint8),
        )
        metadata = {
            **asdict(config),
            "schema_version": SCHEMA_VERSION,
            "git_commit": _git_commit(),
            "physics_hz": physics_hz,
            "control_hz": simulation.config.control_hz,
            "realized_speed_m_s": speed_m_s,
            "probe": {
                "shape": "sphere",
                "diameter_m": 0.045,
                "mass_kg": 0.12,
                "color_rgba": color,
                "start_position_m": start_position.tolist(),
                "contact_target_position_m": contact_position.tolist(),
                "controller": {"position_gain_n_m": 500.0, "velocity_gain_ns_m": 10.0},
            },
            "subject_entity_id": subject_id,
            "observer_entity_id": observer_id,
            "target_link": link_name,
            "joint_names": JOINT_NAMES,
            "body_parameters": body,
            "summary": {
                "peak_contact_force_n": peak_force,
                "contact_impulse_ns": impulse,
                "contact_duration_s": duration,
                "peak_joint_torque_nm": float(np.abs(trajectory["joint_torque"]).max()),
                "accumulated_torque_load_nms": cumulative_load,
                "accumulated_mechanical_work_j": float(
                    trajectory["mechanical_power"].sum() * dt
                ),
            },
        }
        (output_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return metadata
    finally:
        simulation.close()
