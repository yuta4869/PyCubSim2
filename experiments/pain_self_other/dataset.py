"""Resampling, validation, episode splitting, and train-only normalization."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np

from .simulation import JOINT_NAMES

T_NAMES = (
    "contact",
    "normal_force_n",
    "peak_force_n",
    "impulse_ns",
    "duration_s",
    "position_x_m",
    "position_y_m",
    "position_z_m",
    "relative_normal_velocity_m_s",
    "link_id",
)
P_NAMES = tuple(
    [f"{name}_position_rad" for name in JOINT_NAMES]
    + [f"{name}_velocity_rad_s" for name in JOINT_NAMES]
)
I_NAMES = tuple(
    [f"{name}_torque_nm" for name in JOINT_NAMES]
    + [f"{name}_mechanical_power_w" for name in JOINT_NAMES]
    + ["cumulative_torque_load_nms", "filtered_torque_load_nm"]
)


def _interp(time: np.ndarray, values: np.ndarray, query: np.ndarray) -> np.ndarray:
    flat = values.reshape(len(values), -1)
    result = np.column_stack(
        [np.interp(query, time, flat[:, index]) for index in range(flat.shape[1])]
    )
    return result.reshape((len(query),) + values.shape[1:])


def _nearest(time: np.ndarray, values: np.ndarray, query: np.ndarray) -> np.ndarray:
    right = np.searchsorted(time, query, side="left").clip(0, len(time) - 1)
    left = np.maximum(0, right - 1)
    choose_left = np.abs(query - time[left]) <= np.abs(time[right] - query)
    return values[np.where(choose_left, left, right)]


def _downsample_rgb(images: np.ndarray, size: int) -> np.ndarray:
    height, width = images.shape[1:3]
    if height % size == 0 and width % size == 0:
        return images.reshape(
            len(images), size, height // size, size, width // size, 3
        ).mean(axis=(2, 4), dtype=np.float32) / 255.0
    ys = np.linspace(0, height - 1, size).round().astype(int)
    xs = np.linspace(0, width - 1, size).round().astype(int)
    return images[:, ys][:, :, xs].astype(np.float32) / 255.0


def _raw_touch(raw: dict[str, np.ndarray]) -> np.ndarray:
    weights = raw["contact_normal_force"]
    positions = raw["contact_position_on_a"]
    force = raw["contact_force"]
    denominator = np.maximum(weights.sum(axis=1, keepdims=True), 1e-9)
    weighted_position = (positions * weights[..., None]).sum(axis=1) / denominator
    weighted_position[force == 0.0] = 0.0
    max_index = weights.argmax(axis=1)
    rows = np.arange(len(weights))
    relative_velocity = raw["contact_relative_normal_velocity"][rows, max_index]
    link_id = raw["contact_link_id_a"][rows, max_index]
    relative_velocity[force == 0.0] = 0.0
    link_id[force == 0.0] = -1
    return np.column_stack(
        (
            (raw["contact_count"] > 0).astype(np.float32),
            force,
            raw["peak_contact_force"],
            raw["contact_impulse"],
            raw["contact_duration_s"],
            weighted_position,
            relative_velocity,
            link_id,
        )
    ).astype(np.float32)


def resample_episode(
    raw_episode: str | Path,
    processed_root: str | Path,
    *,
    steps: int = 60,
    image_size: int = 16,
) -> Path:
    """Convert one raw episode to a synchronized fixed-length trajectory."""
    raw_dir = Path(raw_episode)
    metadata = json.loads((raw_dir / "metadata.json").read_text(encoding="utf-8"))
    with np.load(raw_dir / "trajectory.npz", allow_pickle=False) as loaded:
        raw = {name: loaded[name] for name in loaded.files}
    with np.load(raw_dir / "rgb.npz", allow_pickle=False) as loaded:
        rgb_time, rgb = loaded["time_s"], loaded["rgb"]
    time = raw["time_s"]
    query = np.linspace(time[0], time[-1], steps)
    touch = _raw_touch(raw)
    touch_continuous = _interp(time, touch, query)
    touch_continuous[:, 0] = _nearest(time, touch[:, 0], query)
    touch_continuous[:, -1] = _nearest(time, touch[:, -1], query)
    rgb_query = _nearest(rgb_time, rgb, query)
    output_dir = Path(processed_root) / raw_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    arrays = {
        "time_s": query.astype(np.float64),
        "time_normalized": np.linspace(0.0, 1.0, steps, dtype=np.float32),
        "X": _downsample_rgb(rgb_query, image_size),
        "T": touch_continuous.astype(np.float32),
        "P": np.concatenate(
            (
                _interp(time, raw["joint_position"], query),
                _interp(time, raw["joint_velocity"], query),
            ),
            axis=1,
        ).astype(np.float32),
        "I": np.concatenate(
            (
                _interp(time, raw["joint_torque"], query),
                _interp(time, raw["mechanical_power"], query),
                _interp(time, raw["cumulative_torque_load"], query)[:, None],
                _interp(time, raw["filtered_torque_load"], query)[:, None],
            ),
            axis=1,
        ).astype(np.float32),
    }
    np.savez_compressed(output_dir / "episode.npz", **arrays)
    metadata["processed"] = {
        "steps": steps,
        "image_shape": [image_size, image_size, 3],
        "modalities": {"X": image_size * image_size * 3, "T": 10, "P": 14, "I": 16},
        "T_names": T_NAMES,
        "P_names": P_NAMES,
        "I_names": I_NAMES,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_dir


def validate_episode(episode: str | Path, *, processed: bool = False) -> list[str]:
    path = Path(episode)
    errors: list[str] = []
    try:
        metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        filename = "episode.npz" if processed else "trajectory.npz"
        with np.load(path / filename, allow_pickle=False) as loaded:
            arrays = {name: loaded[name] for name in loaded.files}
    except Exception as exc:
        return [f"could not load episode: {exc}"]
    time = arrays.get("time_s")
    if time is None or time.ndim != 1 or len(time) < 2:
        errors.append("time_s must be a one-dimensional trajectory")
    elif not np.all(np.diff(time) > 0.0):
        errors.append("time_s must be strictly increasing")
    for name, values in arrays.items():
        if name == "joint_names":
            continue
        if values.dtype.kind in "fc" and not np.all(np.isfinite(values)):
            errors.append(f"{name} contains non-finite values")
    if processed:
        expected = {"X": 4, "T": 2, "P": 2, "I": 2}
        for name, ndim in expected.items():
            if name not in arrays or arrays[name].ndim != ndim:
                errors.append(f"{name} must have {ndim} dimensions")
        if len({arrays[name].shape[0] for name in expected if name in arrays}) > 1:
            errors.append("processed modality lengths are not synchronized")
    elif metadata.get("no_contact") and float(arrays["contact_force"].max()) > 1e-6:
        errors.append("no-contact episode has non-zero contact force")
    return errors


def _condition(metadata: dict) -> tuple[str, ...]:
    return tuple(
        str(metadata.get(name))
        for name in (
            "role",
            "speed",
            "posture",
            "contact_location",
            "body_condition",
            "no_contact",
            "dissociation_condition",
        )
    )


def split_episodes(
    processed_root: str | Path,
    manifest_path: str | Path,
    *,
    seed: int = 20260903,
) -> list[dict[str, str]]:
    """Create a deterministic condition-stratified episode-level split."""
    groups: dict[tuple[str, ...], list[tuple[Path, dict]]] = defaultdict(list)
    for metadata_path in sorted(Path(processed_root).glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        groups[_condition(metadata)].append((metadata_path.parent, metadata))
    rng = np.random.default_rng(seed)
    dissociation_seeds = sorted(
        {
            metadata["seed"]
            for group in groups.values()
            for _, metadata in group
            if metadata.get("dissociation_condition") is not None
        }
    )
    seed_splits = {}
    if dissociation_seeds:
        order = rng.permutation(dissociation_seeds)
        n_test = max(1, round(0.15 * len(order)))
        n_val = max(1, round(0.15 * len(order)))
        seed_splits = {
            int(value): "test" if rank < n_test else "validation" if rank < n_test + n_val else "train"
            for rank, value in enumerate(order)
        }
    rows: list[dict[str, str]] = []
    for group in groups.values():
        order = rng.permutation(len(group))
        n = len(group)
        n_test = max(1, round(0.15 * n)) if n >= 3 else 0
        n_val = max(1, round(0.15 * n)) if n >= 3 else 0
        for rank, index in enumerate(order):
            path, metadata = group[index]
            split = seed_splits.get(
                metadata["seed"],
                "test" if rank < n_test else "validation" if rank < n_test + n_val else "train",
            )
            rows.append(
                {
                    "episode_id": metadata["episode_id"],
                    "path": str(path.resolve()),
                    "split": split,
                    "role": metadata["role"],
                    "speed": metadata["speed"],
                    "posture": metadata["posture"],
                    "contact_location": metadata["contact_location"],
                    "body_condition": metadata["body_condition"],
                    "self_body_condition": str(metadata.get("self_body_condition")),
                    "dissociation_condition": str(metadata.get("dissociation_condition")),
                    "pair_id": str(metadata.get("pair_id")),
                    "no_contact": str(metadata.get("no_contact", False)),
                    "seed": str(metadata["seed"]),
                }
            )
    rows.sort(key=lambda row: row["episode_id"])
    destination = Path(manifest_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["episode_id"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def load_manifest(path: str | Path, split: str | None = None) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return [row for row in rows if split is None or row["split"] == split]


def fit_normalization(
    rows: Iterable[dict[str, str]], output_path: str | Path
) -> dict[str, dict[str, list[float]]]:
    """Fit T/P/I statistics using train rows only."""
    train = [row for row in rows if row["split"] == "train"]
    if not train:
        raise ValueError("normalization requires at least one training episode")
    result: dict[str, dict[str, list[float]]] = {}
    for modality in ("T", "P", "I"):
        values = []
        for row in train:
            with np.load(Path(row["path"]) / "episode.npz", allow_pickle=False) as loaded:
                values.append(loaded[modality])
        joined = np.concatenate(values, axis=0).astype(np.float64)
        mean, scale = joined.mean(axis=0), joined.std(axis=0)
        scale[scale < 1e-6] = 1.0
        result[modality] = {"mean": mean.tolist(), "scale": scale.tolist()}
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def load_processed(
    row: dict[str, str], normalization: dict[str, dict[str, list[float]]] | None = None
) -> dict[str, np.ndarray]:
    with np.load(Path(row["path"]) / "episode.npz", allow_pickle=False) as loaded:
        episode = {name: loaded[name] for name in loaded.files}
    episode["X"] = episode["X"].reshape(len(episode["X"]), -1)
    if normalization:
        for modality in ("T", "P", "I"):
            episode[modality] = (
                episode[modality] - np.asarray(normalization[modality]["mean"])
            ) / np.asarray(normalization[modality]["scale"])
    return episode
