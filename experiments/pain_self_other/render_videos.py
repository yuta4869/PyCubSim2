"""Render synchronized experiment replays from saved RGB and physics arrays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
OUTPUTS = HERE / "outputs"
DEFAULT_OUTPUT = HERE / "reports" / "videos"
PANEL_SIZE = (640, 360)
FPS = 30


def load_episode(path: Path, extra: tuple[str, ...] = ()) -> dict:
    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    with np.load(path / "rgb.npz", allow_pickle=False) as source:
        rgb_time, rgb = source["time_s"].copy(), source["rgb"].copy()
    with np.load(path / "trajectory.npz", allow_pickle=False) as source:
        trajectory = {name: source[name].copy() for name in source.files}
    return {"path": path, "metadata": metadata, "rgb_time": rgb_time, "rgb": rgb, "trajectory": trajectory, "extra": extra}


def phase(time_s: float) -> str:
    if time_s < 0.4:
        return "BASELINE"
    if time_s < 0.9:
        return "APPROACH"
    if time_s < 1.1:
        return "CONTACT"
    if time_s < 1.4:
        return "REMOVAL"
    return "RECOVERY"


def put(canvas: np.ndarray, text: str, point: tuple[int, int], scale: float = 0.47, color=(35, 35, 35), thickness: int = 1) -> None:
    cv2.putText(canvas, text, point, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def panel(episode: dict, frame_index: int, title: str) -> np.ndarray:
    width, height = PANEL_SIZE
    canvas = np.full((height, width, 3), 248, dtype=np.uint8)
    time_s = float(episode["rgb_time"][frame_index])
    trajectory = episode["trajectory"]
    physics_index = int(np.abs(trajectory["time_s"] - time_s).argmin())
    image = cv2.cvtColor(episode["rgb"][frame_index], cv2.COLOR_RGB2BGR)
    image = cv2.resize(image, (300, 300), interpolation=cv2.INTER_NEAREST)
    canvas[44:344, 10:310] = image
    cv2.rectangle(canvas, (9, 43), (311, 345), (95, 95, 95), 1)

    metadata = episode["metadata"]
    force = float(trajectory["contact_force"][physics_index])
    impulse = float(trajectory["contact_impulse"][physics_index])
    peak_torque = float(np.max(np.abs(trajectory["joint_torque"][: physics_index + 1])))
    load = float(trajectory["cumulative_torque_load"][physics_index])
    put(canvas, title, (12, 29), 0.60, (15, 15, 15), 2)
    lines = (
        f"t = {time_s:4.2f} s  |  {phase(time_s)}",
        f"body: {metadata['body_condition']}",
        f"contact force: {force:6.2f} N",
        f"impulse:       {impulse:6.3f} N s",
        f"peak torque:   {peak_torque:6.2f} N m",
        f"load:          {load:6.2f} N m s",
        *episode["extra"],
    )
    line_step = 20 if episode["extra"] else 23
    for index, line in enumerate(lines):
        put(canvas, line, (329, 62 + index * line_step), color=(25, 25, 25))

    plot_x, plot_w = 330, 292
    plot_y, plot_h = (250, 73) if episode["extra"] else (235, 88)
    cv2.rectangle(canvas, (plot_x, plot_y), (plot_x + plot_w, plot_y + plot_h), (150, 150, 150), 1)
    times = trajectory["time_s"]
    forces = trajectory["contact_force"]
    maximum = max(1.0, float(np.max(forces)) * 1.08)
    points = np.column_stack(
        (
            plot_x + np.clip(times / max(times[-1], 1e-9), 0, 1) * plot_w,
            plot_y + plot_h - np.clip(forces / maximum, 0, 1) * plot_h,
        )
    ).astype(np.int32)
    cv2.polylines(canvas, [points], False, (178, 95, 0), 2, cv2.LINE_AA)
    cursor_x = int(plot_x + np.clip(time_s / max(times[-1], 1e-9), 0, 1) * plot_w)
    cv2.line(canvas, (cursor_x, plot_y), (cursor_x, plot_y + plot_h), (0, 90, 220), 1)
    put(canvas, f"contact force history (max {maximum / 1.08:.1f} N)", (plot_x, plot_y - 7), 0.40)
    progress = int((width - 20) * frame_index / max(len(episode["rgb"]) - 1, 1))
    cv2.rectangle(canvas, (10, height - 7), (width - 10, height - 4), (210, 210, 210), -1)
    cv2.rectangle(canvas, (10, height - 7), (10 + progress, height - 4), (0, 120, 190), -1)
    return canvas


def note_panel(lines: tuple[str, ...]) -> np.ndarray:
    width, height = PANEL_SIZE
    canvas = np.full((height, width, 3), 248, dtype=np.uint8)
    put(canvas, "Replay notes", (28, 48), 0.78, (15, 15, 15), 2)
    for index, line in enumerate(lines):
        put(canvas, line, (30, 92 + index * 33), 0.55)
    return canvas


def write_video(path: Path, episodes: tuple[tuple[dict, str], ...], columns: int = 2, repeat: int = 2, note: tuple[str, ...] = ()) -> dict:
    rows = int(np.ceil((len(episodes) + bool(note)) / columns))
    width, height = columns * PANEL_SIZE[0], rows * PANEL_SIZE[1]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Could not open MP4 writer: {path}")
    frame_count = min(len(episode["rgb"]) for episode, _ in episodes)
    for frame_index in range(frame_count):
        panels = [panel(episode, frame_index, title) for episode, title in episodes]
        if note:
            panels.append(note_panel(note))
        panels.extend(np.full((PANEL_SIZE[1], PANEL_SIZE[0], 3), 248, np.uint8) for _ in range(rows * columns - len(panels)))
        canvas = np.vstack([np.hstack(panels[row * columns : (row + 1) * columns]) for row in range(rows)])
        for _ in range(repeat):
            writer.write(canvas)
    writer.release()
    capture = cv2.VideoCapture(str(path))
    actual_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    readable, _ = capture.read()
    capture.release()
    expected_frames = frame_count * repeat
    if not readable or actual_frames != expected_frames:
        raise RuntimeError(f"Invalid video {path}: frames={actual_frames}, expected={expected_frames}")
    return {"file": path.name, "frames": actual_frames, "fps": FPS, "duration_s": actual_frames / FPS, "size": [width, height], "sources": [str(episode["path"].relative_to(HERE)) for episode, _ in episodes]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repeat", type=int, default=2, help="Repeat each source frame; 2 gives 0.5x playback.")
    args = parser.parse_args()
    if args.repeat < 1:
        raise ValueError("--repeat must be at least 1")
    args.output.mkdir(parents=True, exist_ok=True)

    self_root = RAW / "self_full"
    dissociation_root = RAW / "dissociation"
    videos = []
    videos.append(
        write_video(
            args.output / "01_self_physics_speed.mp4",
            tuple(
                (load_episode(self_root / f"S2_{speed}_neutral_hand_r10"), f"SELF: {speed.upper()} / neutral / hand")
                for speed in ("slow", "medium", "fast")
            ),
            repeat=args.repeat,
            note=("Same probe geometry", "Same posture and location", "Only speed condition changes", "RGB + physics synchronized", "Playback: 0.5x"),
        )
    )

    conditions = (
        ("matched_high", "MATCHED HIGH"),
        ("self_high_other_low", "SELF HIGH / OTHER LOW"),
        ("self_low_other_high", "SELF LOW / OTHER HIGH"),
        ("matched_low", "MATCHED LOW"),
    )
    videos.append(
        write_video(
            args.output / "02_other_observation_four_conditions.mp4",
            tuple((load_episode(dissociation_root / f"S7_{condition}_r10_other_actual"), title) for condition, title in conditions),
            repeat=args.repeat,
        )
    )

    mismatch = (
        ("self_high_other_low", "SELF HIGH / OTHER LOW"),
        ("self_low_other_high", "SELF LOW / OTHER HIGH"),
    )
    pair_episodes = []
    for condition, title in mismatch:
        pair_episodes.extend(
            (
                (load_episode(dissociation_root / f"S7_{condition}_r10_self_reference"), f"{title}: SELF REFERENCE"),
                (load_episode(dissociation_root / f"S7_{condition}_r10_other_actual"), f"{title}: OTHER ACTUAL"),
            )
        )
    videos.append(write_video(args.output / "03_self_other_mismatch_pairs.mp4", tuple(pair_episodes), repeat=args.repeat))

    stage7 = json.loads((OUTPUTS / "S7_DISSOCIATION_full" / "metrics.json").read_text(encoding="utf-8"))["conditions"]
    protection_episodes = []
    for condition, title in mismatch:
        result = stage7[condition]
        prediction = float(result["predicted_other_H"])
        action = "INTERVENE" if prediction >= 0.75 else "NO INTERVENTION"
        protection_episodes.append(
            (
                load_episode(
                    dissociation_root / f"S7_{condition}_r10_other_actual",
                    (f"predicted Other H: {prediction:.4f}", "threshold: 0.7500", f"decision: {action}"),
                ),
                f"STAGE 8: {title}",
            )
        )
    videos.append(
        write_video(
            args.output / "04_protection_decision_replay.mp4",
            tuple(protection_episodes),
            repeat=args.repeat,
            note=("Decision uses predicted Other H", "Low Other: correct no action", "High Other: missed intervention", "No post-hoc threshold change", "Playback: 0.5x"),
        )
    )
    manifest = {"source_fps": FPS, "frame_repeat": args.repeat, "videos": videos}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
