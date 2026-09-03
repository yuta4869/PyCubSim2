"""Physical-unit trajectory metrics, baselines, harm readout, and plots."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def trajectory_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    time_s: np.ndarray,
    modality: str,
) -> dict[str, float]:
    error = predicted - actual
    metrics = {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
    }
    if modality == "T":
        actual_contact, predicted_contact = actual[:, 0] >= 0.5, predicted[:, 0] >= 0.5
        metrics.update(
            {
                "contact_onset_error_s": _onset(time_s, predicted_contact)
                - _onset(time_s, actual_contact),
                "peak_force_error_n": float(predicted[:, 1].max() - actual[:, 1].max()),
                "impulse_error_ns": float(predicted[-1, 3] - actual[-1, 3]),
                "peak_time_error_s": float(
                    time_s[predicted[:, 1].argmax()] - time_s[actual[:, 1].argmax()]
                ),
            }
        )
    elif modality == "P":
        metrics["position_mae_rad"] = float(np.mean(np.abs(error[:, :7])))
        metrics["velocity_mae_rad_s"] = float(np.mean(np.abs(error[:, 7:])))
    elif modality == "I":
        metrics.update(
            {
                "peak_torque_error_nm": float(
                    np.abs(predicted[:, :7]).max() - np.abs(actual[:, :7]).max()
                ),
                "accumulated_load_error_nms": float(predicted[-1, 14] - actual[-1, 14]),
                "load_peak_time_error_s": float(
                    time_s[np.abs(predicted[:, :7]).max(axis=1).argmax()]
                    - time_s[np.abs(actual[:, :7]).max(axis=1).argmax()]
                ),
            }
        )
    return metrics


def _onset(time_s: np.ndarray, active: np.ndarray) -> float:
    indices = np.flatnonzero(active)
    return float(time_s[indices[0]]) if len(indices) else float(time_s[-1])


def mean_baseline(train_episodes: list[dict[str, np.ndarray]], modality: str) -> np.ndarray:
    return np.mean([episode[modality] for episode in train_episodes], axis=0)


def physical_summary(T: np.ndarray, I: np.ndarray) -> dict[str, float]:
    return {
        "peak_contact_force_n": float(np.max(T[:, 1])),
        "contact_impulse_ns": float(T[-1, 3]),
        "peak_joint_torque_nm": float(np.max(np.abs(I[:, :7]))),
        "accumulated_torque_load_nms": float(I[-1, 14]),
    }


def fit_harm_scale(episodes: list[dict[str, np.ndarray]]) -> dict[str, float]:
    if not episodes:
        raise ValueError("harm scale requires training episodes")
    summaries = [physical_summary(episode["T"], episode["I"]) for episode in episodes]
    return {
        name: max(1e-6, float(np.quantile([summary[name] for summary in summaries], 0.95)))
        for name in summaries[0]
    }


def harm_readout(
    T: np.ndarray,
    I: np.ndarray,
    scale: dict[str, float],
    *,
    threshold: float = 0.75,
) -> dict[str, float | bool]:
    components = physical_summary(T, I)
    weights = {
        "peak_contact_force_n": 0.35,
        "contact_impulse_ns": 0.25,
        "peak_joint_torque_nm": 0.20,
        "accumulated_torque_load_nms": 0.20,
    }
    action = sum(
        weights[name] * np.clip(value / scale[name], 0.0, 2.0)
        for name, value in components.items()
    )
    return {
        **components,
        "H_action": float(action),
        "threshold": threshold,
        "intervene": bool(action >= threshold),
    }


def save_metrics(metrics: object, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")


def plot_physics(rows: list[dict[str, float | str]], output: str | Path) -> None:
    import matplotlib.pyplot as plt

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    labels = [str(row["episode_id"]) for row in rows]
    figure, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    fields = (
        ("peak_contact_force_n", "Peak force [N]"),
        ("contact_impulse_ns", "Impulse [N s]"),
        ("peak_joint_torque_nm", "Peak torque [N m]"),
        ("accumulated_torque_load_nms", "Accumulated torque load [N m s]"),
    )
    for axis, (field, title) in zip(axes.flat, fields):
        axis.bar(range(len(rows)), [float(row[field]) for row in rows])
        axis.set_title(title)
        axis.set_xticks(range(len(rows)), labels, rotation=70, ha="right", fontsize=7)
        axis.grid(axis="y", alpha=0.25)
    figure.savefig(destination, dpi=150)
    plt.close(figure)


def plot_predictions(
    time_s: np.ndarray,
    actual: dict[str, np.ndarray],
    predicted: dict[str, np.ndarray],
    output: str | Path,
    *,
    self_counterfactual: dict[str, np.ndarray] | None = None,
) -> None:
    import matplotlib.pyplot as plt

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True, constrained_layout=True)
    series = (
        ("T", 1, "Contact force [N]"),
        ("P", 3, "Elbow position [rad]"),
        ("I", 3, "Elbow torque [N m]"),
    )
    for axis, (modality, index, label) in zip(axes, series):
        axis.plot(time_s, actual[modality][:, index], label="Actual Other", color="black")
        axis.plot(time_s, predicted[modality][:, index], label="Predicted Other", color="tab:blue")
        if self_counterfactual:
            axis.plot(
                time_s,
                self_counterfactual[modality][:, index],
                label="Self counterfactual",
                color="tab:orange",
                linestyle="--",
            )
        axis.set_ylabel(label)
        axis.grid(alpha=0.25)
    axes[-1].set_xlabel("Time [s]")
    axes[0].legend()
    figure.savefig(destination, dpi=150)
    plt.close(figure)
