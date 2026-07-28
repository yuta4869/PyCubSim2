from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


BUILTIN_BEHAVIORS = (
    "Manual pose",
    "Idle breathing",
    "Look around",
    "Right arm wave",
    "Left arm wave",
    "Both arms wave",
    "Whole-body tilt",
    "Random motion",
    "Keyframe action",
)

MANUAL_JOINT_NAMES = (
    "torso_pitch",
    "torso_roll",
    "torso_yaw",
    "neck_pitch",
    "neck_roll",
    "neck_yaw",
    "eyes_tilt",
    "r_shoulder_pitch",
    "r_shoulder_roll",
    "r_shoulder_yaw",
    "r_elbow",
    "r_wrist_prosup",
    "r_wrist_pitch",
    "r_wrist_yaw",
    "l_shoulder_pitch",
    "l_shoulder_roll",
    "l_shoulder_yaw",
    "l_elbow",
    "l_wrist_prosup",
    "l_wrist_pitch",
    "l_wrist_yaw",
)

DEFAULT_POSE_DEG = {
    "torso_pitch": 0.0,
    "torso_roll": 0.0,
    "torso_yaw": 0.0,
    "neck_pitch": -4.0,
    "neck_roll": 0.0,
    "neck_yaw": 0.0,
    "eyes_tilt": -24.0,
    "r_shoulder_pitch": -35.0,
    "r_shoulder_roll": 32.0,
    "r_shoulder_yaw": 4.0,
    "r_elbow": 58.0,
    "r_wrist_prosup": 0.0,
    "r_wrist_pitch": 0.0,
    "r_wrist_yaw": 0.0,
    "l_shoulder_pitch": -35.0,
    "l_shoulder_roll": 32.0,
    "l_shoulder_yaw": -4.0,
    "l_elbow": 58.0,
    "l_wrist_prosup": 0.0,
    "l_wrist_pitch": 0.0,
    "l_wrist_yaw": 0.0,
}


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


@dataclass(frozen=True)
class Keyframe:
    time_s: float
    joints_deg: dict[str, float]
    left_grip: float | None = None
    right_grip: float | None = None


@dataclass(frozen=True)
class KeyframeAction:
    name: str
    duration_s: float
    loop: bool
    keyframes: tuple[Keyframe, ...]
    source_path: Path

    @classmethod
    def load(cls, path: str | Path) -> "KeyframeAction":
        source = Path(path).resolve()
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read action: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Action file must contain a JSON object.")
        raw_frames = data.get("keyframes")
        if not isinstance(raw_frames, list) or len(raw_frames) < 1:
            raise ValueError("Action must contain at least one keyframe.")
        frames: list[Keyframe] = []
        for raw in raw_frames:
            if not isinstance(raw, dict):
                raise ValueError("Each keyframe must be a JSON object.")
            time_s = float(raw.get("time", raw.get("time_s", 0.0)))
            if not math.isfinite(time_s) or time_s < 0.0:
                raise ValueError("Keyframe times must be finite and non-negative.")
            joints = raw.get("joints", {})
            if not isinstance(joints, dict):
                raise ValueError("Keyframe joints must be an object.")
            joints_deg = {}
            for name, value in joints.items():
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError(f"Joint value for {name} must be finite.")
                joints_deg[str(name)] = value
            left_grip = raw.get("left_grip")
            right_grip = raw.get("right_grip")
            frames.append(
                Keyframe(
                    time_s=time_s,
                    joints_deg=joints_deg,
                    left_grip=None if left_grip is None else clamp(left_grip, 0.0, 1.0),
                    right_grip=None if right_grip is None else clamp(right_grip, 0.0, 1.0),
                )
            )
        frames.sort(key=lambda frame: frame.time_s)
        duration = float(data.get("duration", frames[-1].time_s))
        duration = max(duration, frames[-1].time_s, 0.001)
        return cls(
            name=str(data.get("name", source.stem)),
            duration_s=duration,
            loop=bool(data.get("loop", False)),
            keyframes=tuple(frames),
            source_path=source,
        )

    def sample(self, elapsed_s: float) -> tuple[dict[str, float], float | None, float | None, bool]:
        if self.loop:
            local_time = elapsed_s % self.duration_s
            finished = False
        else:
            local_time = min(elapsed_s, self.duration_s)
            finished = elapsed_s >= self.duration_s
        before = self.keyframes[0]
        after = self.keyframes[-1]
        for index, frame in enumerate(self.keyframes):
            if frame.time_s <= local_time:
                before = frame
            if frame.time_s >= local_time:
                after = frame
                break
        if after.time_s <= before.time_s:
            fraction = 0.0
        else:
            fraction = (local_time - before.time_s) / (after.time_s - before.time_s)
        names = set(before.joints_deg) | set(after.joints_deg)
        joints = {}
        for name in names:
            start = before.joints_deg.get(name, after.joints_deg.get(name, 0.0))
            end = after.joints_deg.get(name, start)
            joints[name] = math.radians(start + fraction * (end - start))

        def interpolated_grip(side: str) -> float | None:
            start = getattr(before, side)
            end = getattr(after, side)
            if start is None:
                start = end
            if end is None:
                end = start
            if start is None or end is None:
                return None
            return float(start + fraction * (end - start))

        return (
            joints,
            interpolated_grip("left_grip"),
            interpolated_grip("right_grip"),
            finished,
        )


class RandomBehavior:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.next_change_s = 0.0
        self.targets: dict[str, float] = {}

    def reset(self) -> None:
        self.next_change_s = 0.0
        self.targets = {}

    def targets_for(self, elapsed_s: float, intensity: float) -> dict[str, float]:
        if elapsed_s >= self.next_change_s or not self.targets:
            self.next_change_s = elapsed_s + self.rng.uniform(1.0, 2.8)
            amount = clamp(intensity, 0.0, 1.0)
            self.targets = {
                "torso_pitch": math.radians(self.rng.uniform(-8.0, 10.0) * amount),
                "torso_roll": math.radians(self.rng.uniform(-6.0, 6.0) * amount),
                "torso_yaw": math.radians(self.rng.uniform(-14.0, 14.0) * amount),
                "neck_pitch": math.radians(self.rng.uniform(-15.0, 8.0) * amount),
                "neck_roll": math.radians(self.rng.uniform(-7.0, 7.0) * amount),
                "neck_yaw": math.radians(self.rng.uniform(-40.0, 40.0) * amount),
                "r_shoulder_pitch": math.radians(self.rng.uniform(-60.0, -18.0)),
                "r_shoulder_roll": math.radians(self.rng.uniform(18.0, 72.0)),
                "r_shoulder_yaw": math.radians(self.rng.uniform(-18.0, 28.0) * amount),
                "r_elbow": math.radians(self.rng.uniform(42.0, 96.0)),
                "l_shoulder_pitch": math.radians(self.rng.uniform(-60.0, -18.0)),
                "l_shoulder_roll": math.radians(self.rng.uniform(18.0, 72.0)),
                "l_shoulder_yaw": math.radians(self.rng.uniform(-28.0, 18.0) * amount),
                "l_elbow": math.radians(self.rng.uniform(42.0, 96.0)),
            }
        return dict(self.targets)


def home_targets() -> dict[str, float]:
    return {
        name: math.radians(value)
        for name, value in DEFAULT_POSE_DEG.items()
    }


def behavior_targets(
    behavior: str,
    elapsed_s: float,
    speed: float,
    intensity: float,
    manual_deg: dict[str, float],
    random_behavior: RandomBehavior,
) -> dict[str, float]:
    targets = home_targets()
    targets.update(
        {
            name: math.radians(value)
            for name, value in manual_deg.items()
        }
    )
    amount = clamp(intensity, 0.0, 1.0)
    phase = 2.0 * math.pi * max(0.05, speed) * elapsed_s

    if behavior == "Idle breathing":
        targets["torso_pitch"] = math.radians(4.0 * amount * math.sin(phase * 0.35))
        targets["neck_pitch"] = math.radians(
            -4.0 + 3.0 * amount * math.sin(phase * 0.35 + 0.6)
        )
    elif behavior == "Look around":
        targets["neck_yaw"] = math.radians(38.0 * amount * math.sin(phase * 0.45))
        targets["neck_pitch"] = math.radians(
            -6.0 + 11.0 * amount * math.sin(phase * 0.28)
        )
        targets["neck_roll"] = math.radians(5.0 * amount * math.sin(phase * 0.31))
    elif behavior in {"Right arm wave", "Both arms wave"}:
        targets["r_shoulder_pitch"] = math.radians(-50.0)
        targets["r_shoulder_roll"] = math.radians(
            62.0 + 15.0 * amount * math.sin(phase * 0.7)
        )
        targets["r_shoulder_yaw"] = math.radians(8.0)
        targets["r_elbow"] = math.radians(
            72.0 + 24.0 * amount * math.sin(phase + 0.7)
        )
    if behavior in {"Left arm wave", "Both arms wave"}:
        targets["l_shoulder_pitch"] = math.radians(-50.0)
        targets["l_shoulder_roll"] = math.radians(
            62.0 + 15.0 * amount * math.sin(phase * 0.7 + math.pi)
        )
        targets["l_shoulder_yaw"] = math.radians(-8.0)
        targets["l_elbow"] = math.radians(
            72.0 + 24.0 * amount * math.sin(phase + math.pi + 0.7)
        )
    elif behavior == "Whole-body tilt":
        targets["torso_pitch"] = math.radians(12.0 * amount * math.sin(phase * 0.35))
        targets["torso_roll"] = math.radians(8.0 * amount * math.sin(phase * 0.27))
        targets["neck_pitch"] = math.radians(-8.0 * amount)
        targets["r_shoulder_pitch"] = math.radians(
            -35.0 + 9.0 * amount * math.sin(phase)
        )
        targets["l_shoulder_pitch"] = math.radians(
            -35.0 - 9.0 * amount * math.sin(phase)
        )
    elif behavior == "Random motion":
        targets.update(random_behavior.targets_for(elapsed_s * max(0.05, speed), amount))
    return targets


def finger_closed_value(name: str, lower: float, upper: float) -> float:
    if "thumb_0" in name:
        value = 0.55
    elif "index_0" in name:
        value = -0.18
    elif name.endswith("_0_joint"):
        value = 0.18
    else:
        value = 1.0
    return float(np.clip(value, lower, upper))

