"""Command-line runner for the physical Self/Other DMBN experiment."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from itertools import product
from pathlib import Path

import numpy as np

from .dataset import (
    fit_normalization,
    load_manifest,
    load_processed,
    resample_episode,
    split_episodes,
    validate_episode,
)
from .dmbn import DMBN, DMBNConfig, train
from .evaluate import (
    fit_harm_scale,
    harm_readout,
    physical_summary,
    plot_predictions,
    save_metrics,
    trajectory_metrics,
)
from .simulation import EpisodeConfig, run_episode

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data"


def _self_configs(repetitions: int, seed: int, controls: bool) -> list[EpisodeConfig]:
    configs = []
    for index, (speed, posture, location, repetition) in enumerate(
        product(
            ("slow", "medium", "fast"),
            ("flexed", "neutral", "extended"),
            ("hand", "forearm"),
            range(repetitions),
        )
    ):
        configs.append(
            EpisodeConfig(
                f"S2_{speed}_{posture}_{location}_r{repetition:02d}",
                seed + index,
                speed=speed,
                posture=posture,
                contact_location=location,
            )
        )
    if controls:
        for offset, speed in enumerate(("slow", "medium", "fast"), len(configs)):
            configs.append(
                EpisodeConfig(
                    f"S1_no_contact_{speed}",
                    seed + offset,
                    speed=speed,
                    no_contact=True,
                )
            )
    return configs


def _dissociation_configs(repetitions: int, seed: int) -> list[EpisodeConfig]:
    conditions = (
        ("matched_high", "rigid", "rigid"),
        ("self_high_other_low", "rigid", "compliant"),
        ("self_low_other_high", "compliant", "rigid"),
        ("matched_low", "compliant", "compliant"),
    )
    configs = []
    for condition_index, (condition, self_body, other_body) in enumerate(conditions):
        for repetition in range(repetitions):
            pair_id = f"S7_{condition}_r{repetition:02d}"
            event_seed = seed + repetition
            shared = {
                "seed": event_seed,
                "speed": "fast",
                "posture": "neutral",
                "contact_location": "hand",
                "pair_id": pair_id,
                "self_body_condition": self_body,
                "dissociation_condition": condition,
            }
            configs.extend(
                (
                    EpisodeConfig(
                        f"{pair_id}_other_actual",
                        role="other",
                        body_condition=other_body,
                        **shared,
                    ),
                    EpisodeConfig(
                        f"{pair_id}_self_reference",
                        role="self",
                        body_condition=self_body,
                        **shared,
                    ),
                )
            )
    return configs


def generate(args: argparse.Namespace) -> None:
    configs = (
        _self_configs(args.repetitions, args.seed, args.controls)
        if args.design == "self"
        else _dissociation_configs(args.repetitions, args.seed)
    )
    output = Path(args.output)
    for index, config in enumerate(configs, 1):
        metadata = output / config.episode_id / "metadata.json"
        if not metadata.exists() or args.overwrite:
            run_episode(config, output)
        if index == 1 or index % 10 == 0 or index == len(configs):
            print(f"generated {index}/{len(configs)} episodes", flush=True)


def prepare(args: argparse.Namespace) -> None:
    raw, processed = Path(args.raw), Path(args.processed)
    episodes = sorted(path.parent for path in raw.glob("*/metadata.json"))
    if not episodes:
        raise ValueError(f"No raw episodes found in {raw}")
    failures = []
    for episode in episodes:
        failures.extend(f"{episode.name}: {error}" for error in validate_episode(episode))
        destination = resample_episode(
            episode, processed, steps=args.steps, image_size=args.image_size
        )
        failures.extend(
            f"{episode.name}: {error}"
            for error in validate_episode(destination, processed=True)
        )
    if failures:
        raise ValueError("\n".join(failures))
    rows = split_episodes(processed, args.manifest, seed=args.seed)
    fit_normalization(rows, args.normalization)
    print(f"prepared {len(rows)} valid episodes", flush=True)


def _rows(args: argparse.Namespace, split: str) -> list[dict[str, str]]:
    rows = load_manifest(args.manifest, split)
    if args.role != "all":
        rows = [row for row in rows if row["role"] == args.role]
    if getattr(args, "body_condition", "all") != "all":
        rows = [
            row for row in rows if row["body_condition"] == args.body_condition
        ]
    return rows


def _normalization(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def train_model(args: argparse.Namespace) -> None:
    normalization = _normalization(args.normalization)
    training_rows = _rows(args, "train")
    if args.fraction < 1.0:
        rng = np.random.default_rng(args.seed)
        groups = defaultdict(list)
        for row in training_rows:
            groups[row.get("dissociation_condition", "all")].append(row)
        training_rows = [
            row
            for group in groups.values()
            for row in np.asarray(group, dtype=object)[
                rng.permutation(len(group))[: max(1, round(args.fraction * len(group)))]
            ]
        ]
    training = [load_processed(row, normalization) for row in training_rows]
    validation = [load_processed(row, normalization) for row in _rows(args, "validation")]
    modalities = tuple(args.modalities)
    if not training:
        raise ValueError("No training episodes match the requested role")
    if not validation:
        raise ValueError("No validation episodes match the requested role")
    dimensions = {name: int(training[0][name].shape[1]) for name in modalities}
    model = DMBN(
        DMBNConfig(
            dimensions=dimensions,
            latent_size=args.latent_size,
            hidden_size=args.hidden_size,
            trunk_size=args.trunk_size,
            seed=args.seed,
            loss_weights={
                modality: 1.0 if modality == "X" else args.nonvisual_weight
                for modality in modalities
            },
        )
    )
    history = train(
        model,
        training,
        validation,
        args.output,
        steps=args.steps,
        learning_rate=args.learning_rate,
        obs_max=args.obs_max,
        validate_every=args.validate_every,
        patience=args.patience,
    )
    metadata = {
        "modalities": modalities,
        "parameters": model.parameter_count(),
        "train_episodes": len(training),
        "training_fraction_requested": args.fraction,
        "validation_episodes": len(validation),
        "seed": args.seed,
        "nonvisual_loss_weight": args.nonvisual_weight,
        "steps_requested": args.steps,
        "steps_executed": int(history[-1]["step"]),
        "best_validation_nll": min(item["validation_nll"] for item in history),
    }
    save_metrics(metadata, Path(args.output) / "run_metadata.json")
    print(json.dumps(metadata, indent=2), flush=True)


def _inverse(
    modality: str, values: np.ndarray, normalization: dict
) -> np.ndarray:
    if modality == "X":
        return values
    return (
        values * np.asarray(normalization[modality]["scale"])
        + np.asarray(normalization[modality]["mean"])
    )


def _average(records: list[dict[str, float]]) -> dict[str, float]:
    keys = records[0] if records else ()
    return {
        key: float(np.mean([record[key] for record in records if np.isfinite(record[key])]))
        for key in keys
        if any(np.isfinite(record[key]) for record in records)
    }


def evaluate_model(args: argparse.Namespace) -> None:
    model = DMBN.load(args.model)
    normalization = _normalization(args.normalization)
    rows = _rows(args, args.split)
    training_rows = _rows(args, "train")
    if not rows or not training_rows:
        raise ValueError("Evaluation requires matching test and training rows")
    context_modalities = tuple(args.context)
    unknown = set(context_modalities) - set(model.modalities)
    if unknown:
        raise ValueError(f"Context modalities absent from model: {sorted(unknown)}")
    train_physical = [load_processed(row) for row in training_rows]
    baselines = {
        modality: np.mean([episode[modality] for episode in train_physical], axis=0)
        for modality in model.modalities
    }
    output = Path(args.output)
    records: list[dict] = []
    per_modality: dict[str, list[dict[str, float]]] = defaultdict(list)
    per_baseline: dict[str, list[dict[str, float]]] = defaultdict(list)
    for row in rows:
        normalized = load_processed(row, normalization)
        physical = load_processed(row)
        mask = normalized["time_normalized"] <= args.context_until
        contexts = {
            modality: np.column_stack(
                (normalized["time_normalized"][mask], normalized[modality][mask])
            )
            for modality in context_modalities
        }
        prediction = model.predict(
            contexts,
            context_modalities,
            normalized["time_normalized"],
        )
        means = {
            modality: _inverse(modality, values["mean"], normalization)
            for modality, values in prediction.items()
        }
        scales = {
            modality: values["scale"]
            * (1.0 if modality == "X" else np.asarray(normalization[modality]["scale"]))
            for modality, values in prediction.items()
        }
        episode_metrics = {}
        for modality in model.modalities:
            metrics = trajectory_metrics(
                physical[modality], means[modality], physical["time_s"], modality
            )
            baseline_metrics = trajectory_metrics(
                physical[modality], baselines[modality], physical["time_s"], modality
            )
            per_modality[modality].append(metrics)
            per_baseline[modality].append(baseline_metrics)
            episode_metrics[modality] = metrics
        records.append({"episode_id": row["episode_id"], "metrics": episode_metrics})
        prediction_path = output / "predictions" / f"{row['episode_id']}.npz"
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            prediction_path,
            time_s=physical["time_s"],
            **{f"{name}_actual": physical[name] for name in model.modalities},
            **{f"{name}_mean": means[name] for name in model.modalities},
            **{f"{name}_scale": scales[name] for name in model.modalities},
        )
        if len(records) == 1 and {"T", "P", "I"}.issubset(model.modalities):
            plot_predictions(
                physical["time_s"],
                physical,
                means,
                output / "figures" / "trajectory_completion.png",
            )
    summary = {
        "model": str(Path(args.model).resolve()),
        "context": context_modalities,
        "context_until": args.context_until,
        "episodes": len(rows),
        "metrics": {name: _average(values) for name, values in per_modality.items()},
        "mean_baseline": {name: _average(values) for name, values in per_baseline.items()},
        "per_episode": records,
    }
    save_metrics(summary, output / "metrics.json")
    print(json.dumps({key: value for key, value in summary.items() if key != "per_episode"}, indent=2))


def _eta_squared(rows: list[dict], factor: str, outcome: str) -> float:
    values = np.asarray([row[outcome] for row in rows], dtype=float)
    grand = values.mean()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[factor]].append(row[outcome])
    between = sum(len(group) * (np.mean(group) - grand) ** 2 for group in grouped.values())
    total = float(np.sum((values - grand) ** 2))
    return float(between / total) if total else 0.0


def _physics_figure(rows: list[dict], output: Path) -> None:
    import matplotlib.pyplot as plt

    fields = (
        ("speed", "peak_contact_force_n", "Speed", "Peak force [N]"),
        ("speed", "contact_impulse_ns", "Speed", "Impulse [N s]"),
        ("posture", "peak_joint_torque_nm", "Posture", "Peak torque [N m]"),
        (
            "posture",
            "accumulated_torque_load_nms",
            "Posture",
            "Accumulated torque load [N m s]",
        ),
    )
    figure, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    for axis, (factor, outcome, xlabel, ylabel) in zip(axes.flat, fields):
        labels = sorted({row[factor] for row in rows})
        axis.boxplot(
            [[row[outcome] for row in rows if row[factor] == label] for label in labels],
            tick_labels=labels,
        )
        axis.set_xlabel(xlabel)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", alpha=0.25)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=150)
    plt.close(figure)


def _example_figure(raw_episode: Path, output: Path) -> None:
    import matplotlib.pyplot as plt

    with np.load(raw_episode / "trajectory.npz", allow_pickle=False) as data:
        time = data["time_s"]
        series = (
            (data["contact_force"], "T: contact force [N]"),
            (data["joint_position"][:, 3], "P: elbow position [rad]"),
            (data["joint_torque"][:, 3], "I: elbow torque [N m]"),
        )
    with np.load(raw_episode / "rgb.npz", allow_pickle=False) as data:
        frame = data["rgb"][len(data["rgb"]) // 2]
    figure, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    axes[0, 0].imshow(frame)
    axes[0, 0].set_title("X: left-eye RGB")
    axes[0, 0].axis("off")
    for axis, (values, label) in zip((axes[0, 1], axes[1, 0], axes[1, 1]), series):
        axis.plot(time, values)
        axis.set_xlabel("Time [s]")
        axis.set_ylabel(label)
        axis.grid(alpha=0.25)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=150)
    plt.close(figure)


def physics_report(args: argparse.Namespace) -> None:
    raw = Path(args.raw)
    metadata = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(raw.glob("*/metadata.json"))
    ]
    contacts = [
        {
            "episode_id": item["episode_id"],
            "speed": item["speed"],
            "posture": item["posture"],
            "contact_location": item["contact_location"],
            **item["summary"],
        }
        for item in metadata
        if item["role"] == "self" and not item["no_contact"]
    ]
    controls = [item for item in metadata if item["no_contact"]]
    if not contacts:
        raise ValueError("Physics report requires Self contact episodes")
    effects = {
        "speed_peak_force_eta_squared": _eta_squared(
            contacts, "speed", "peak_contact_force_n"
        ),
        "speed_impulse_eta_squared": _eta_squared(
            contacts, "speed", "contact_impulse_ns"
        ),
        "posture_peak_torque_eta_squared": _eta_squared(
            contacts, "posture", "peak_joint_torque_nm"
        ),
        "posture_load_eta_squared": _eta_squared(
            contacts, "posture", "accumulated_torque_load_nms"
        ),
    }
    gate = {
        "contact_nonzero": bool(min(row["peak_contact_force_n"] for row in contacts) > 0.0),
        "no_contact_near_zero": bool(
            controls and max(item["summary"]["peak_contact_force_n"] for item in controls) < 1e-6
        ),
        "speed_effect": bool(
            max(effects["speed_peak_force_eta_squared"], effects["speed_impulse_eta_squared"])
            >= 0.01
        ),
        "posture_effect": bool(
            max(effects["posture_peak_torque_eta_squared"], effects["posture_load_eta_squared"])
            >= 0.01
        ),
    }
    grouped = defaultdict(list)
    for row in contacts:
        grouped[(row["speed"], row["posture"], row["contact_location"])].append(row)
    table = []
    for condition, group in sorted(grouped.items()):
        table.append(
            (*condition, len(group))
            + tuple(
                float(np.mean([item[field] for item in group]))
                for field in (
                    "peak_contact_force_n",
                    "contact_impulse_ns",
                    "peak_joint_torque_nm",
                    "accumulated_torque_load_nms",
                )
            )
        )
    output = Path(args.output)
    figure_dir = output.parent.parent / "outputs" / "figures"
    _physics_figure(contacts, figure_dir / "stage2_physics_factors.png")
    example = raw / max(contacts, key=lambda row: row["peak_contact_force_n"])["episode_id"]
    _example_figure(example, figure_dir / "stage2_example_xtpi.png")
    lines = [
        "# Stage 2 Physics Validation",
        "",
        "## Known objective facts",
        "",
        f"**{len(contacts)} physical Self-contact episodes** and **{len(controls)} no-contact controls** were executed.",
        "",
        "| Speed | Posture | Location | n | Peak force N | Impulse N s | Peak torque N m | Load N m s |",
        "|---|---|---|---:|---:|---:|---:|---:|",
        *[
            f"| {speed} | {posture} | {location} | {count} | {force:.4f} | {impulse:.4f} | {torque:.4f} | {load:.4f} |"
            for speed, posture, location, count, force, impulse, torque, load in table
        ],
        "",
        "### Effect sizes",
        "",
        *[f"- **{name}**: {value:.4f}" for name, value in effects.items()],
        "",
        "### Automatic gate",
        "",
        *[f"- **{name}**: {'PASS' if value else 'FAIL'}" for name, value in gate.items()],
        "",
        "## Fact-based analysis",
        "",
        "The gate requires real contact, zero-force controls, and at least a small (eta-squared >= 0.01) speed and posture association. It does not assert causality or subjective pain.",
        "",
        "## Figures",
        "",
        f"- `{figure_dir / 'stage2_physics_factors.png'}`",
        f"- `{figure_dir / 'stage2_example_xtpi.png'}`",
        "",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    save_metrics(
        {"episodes": len(contacts), "controls": len(controls), "effects": effects, "gate": gate},
        output.with_suffix(".json"),
    )
    print(json.dumps({"effects": effects, "gate": gate}, indent=2), flush=True)
    if not all(gate.values()):
        raise RuntimeError("Stage 2 physics gate failed")


def harm_report(args: argparse.Namespace) -> None:
    rows = load_manifest(args.manifest)
    train_rows = [row for row in rows if row["split"] == "train" and row["role"] == args.role]
    test_rows = [row for row in rows if row["split"] == args.split and row["role"] == args.role]
    scale = fit_harm_scale([load_processed(row) for row in train_rows])
    records = []
    for row in test_rows:
        actual = load_processed(row)
        with np.load(Path(args.predictions) / f"{row['episode_id']}.npz", allow_pickle=False) as data:
            predicted_t, predicted_i = data["T_mean"], data["I_mean"]
        actual_readout = harm_readout(actual["T"], actual["I"], scale)
        predicted_readout = harm_readout(predicted_t, predicted_i, scale)
        records.append(
            {
                "episode_id": row["episode_id"],
                "actual": actual_readout,
                "predicted": predicted_readout,
                "correct_decision": actual_readout["intervene"] == predicted_readout["intervene"],
            }
        )
    result = {
        "harm_scale_training_q95": scale,
        "threshold": 0.75,
        "episodes": len(records),
        "decision_accuracy": float(np.mean([record["correct_decision"] for record in records])),
        "intervention_rate_actual": float(
            np.mean([record["actual"]["intervene"] for record in records])
        ),
        "intervention_rate_predicted": float(
            np.mean([record["predicted"]["intervene"] for record in records])
        ),
        "records": records,
    }
    save_metrics(result, args.output)
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, indent=2))


def _predict_physical(
    model: DMBN,
    source: dict[str, np.ndarray],
    normalization: dict,
    context_until: float,
    *,
    time_shift: float = 0.0,
) -> dict[str, np.ndarray]:
    mask = source["time_normalized"] <= context_until
    context_time = np.clip(source["time_normalized"][mask] + time_shift, 0.0, 1.0)
    prediction = model.predict(
        {"X": np.column_stack((context_time, source["X"][mask]))},
        ("X",),
        source["time_normalized"],
    )
    return {
        modality: _inverse(modality, prediction[modality]["mean"], normalization)
        for modality in ("T", "P", "I")
    }


def dissociation_report(args: argparse.Namespace) -> None:
    normalization = _normalization(args.normalization)
    models = {
        ("self", "rigid"): DMBN.load(args.self_rigid_model),
        ("self", "compliant"): DMBN.load(args.self_compliant_model),
        ("other", "rigid"): DMBN.load(args.other_rigid_model),
        ("other", "compliant"): DMBN.load(args.other_compliant_model),
    }
    rows = load_manifest(args.manifest)
    training = [load_processed(row) for row in rows if row["split"] == "train"]
    scale = fit_harm_scale(training)
    pairs = defaultdict(dict)
    for row in rows:
        if row["split"] == args.split and row.get("pair_id") not in {None, "None"}:
            pairs[row["pair_id"]][row["role"]] = row
    output = Path(args.output)
    records, errors = [], defaultdict(lambda: defaultdict(list))
    for pair_id, pair in sorted(pairs.items()):
        if set(pair) != {"self", "other"}:
            continue
        self_row, other_row = pair["self"], pair["other"]
        self_body = other_row["self_body_condition"]
        other_body = other_row["body_condition"]
        source = load_processed(other_row, normalization)
        actual_self, actual_other = load_processed(self_row), load_processed(other_row)
        self_cf = _predict_physical(
            models[("self", self_body)], source, normalization, args.context_until
        )
        other_prediction = _predict_physical(
            models[("other", other_body)], source, normalization, args.context_until
        )
        shuffled = _predict_physical(
            models[("other", "compliant" if other_body == "rigid" else "rigid")],
            source,
            normalization,
            args.context_until,
        )
        shifted = _predict_physical(
            models[("other", other_body)],
            source,
            normalization,
            args.context_until,
            time_shift=0.25,
        )
        predictions = {
            "self_counterfactual": (actual_self, self_cf),
            "other": (actual_other, other_prediction),
            "self_projection": (actual_other, self_cf),
            "shuffled_body_context": (actual_other, shuffled),
            "time_shift": (actual_other, shifted),
        }
        episode_metrics = {}
        for name, (actual, predicted) in predictions.items():
            episode_metrics[name] = {}
            for modality in ("T", "P", "I"):
                metrics = trajectory_metrics(
                    actual[modality], predicted[modality], actual["time_s"], modality
                )
                episode_metrics[name][modality] = metrics
                errors[name][modality].append(metrics)
        actual_self_harm = harm_readout(actual_self["T"], actual_self["I"], scale)
        actual_other_harm = harm_readout(actual_other["T"], actual_other["I"], scale)
        self_cf_harm = harm_readout(self_cf["T"], self_cf["I"], scale)
        other_harm = harm_readout(other_prediction["T"], other_prediction["I"], scale)
        self_summary, other_summary = physical_summary(self_cf["T"], self_cf["I"]), physical_summary(
            other_prediction["T"], other_prediction["I"]
        )
        records.append(
            {
                "pair_id": pair_id,
                "condition": other_row["dissociation_condition"],
                "self_body_condition": self_body,
                "other_body_condition": other_body,
                "actual_self_harm": actual_self_harm,
                "predicted_self_cf_harm": self_cf_harm,
                "actual_other_harm": actual_other_harm,
                "predicted_other_harm": other_harm,
                "delta_force_predicted_n": other_summary["peak_contact_force_n"]
                - self_summary["peak_contact_force_n"],
                "delta_load_predicted_nms": other_summary["accumulated_torque_load_nms"]
                - self_summary["accumulated_torque_load_nms"],
                "metrics": episode_metrics,
            }
        )
        prediction_path = output / "predictions" / f"{pair_id}.npz"
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            prediction_path,
            time_s=actual_other["time_s"],
            **{f"self_actual_{name}": actual_self[name] for name in ("T", "P", "I")},
            **{f"self_cf_{name}": self_cf[name] for name in ("T", "P", "I")},
            **{f"other_actual_{name}": actual_other[name] for name in ("T", "P", "I")},
            **{f"other_predicted_{name}": other_prediction[name] for name in ("T", "P", "I")},
        )
        if other_row["dissociation_condition"] in {
            "self_high_other_low",
            "self_low_other_high",
        } and not (output / "figures" / f"{other_row['dissociation_condition']}.png").exists():
            plot_predictions(
                actual_other["time_s"],
                actual_other,
                other_prediction,
                output / "figures" / f"{other_row['dissociation_condition']}.png",
                self_counterfactual=self_cf,
            )
    aggregate = {
        name: {modality: _average(values) for modality, values in modalities.items()}
        for name, modalities in errors.items()
    }
    by_condition = {}
    for condition in sorted({record["condition"] for record in records}):
        group = [record for record in records if record["condition"] == condition]
        by_condition[condition] = {
            "n": len(group),
            "actual_self_H": float(np.mean([item["actual_self_harm"]["H_action"] for item in group])),
            "predicted_self_cf_H": float(
                np.mean([item["predicted_self_cf_harm"]["H_action"] for item in group])
            ),
            "actual_other_H": float(np.mean([item["actual_other_harm"]["H_action"] for item in group])),
            "predicted_other_H": float(
                np.mean([item["predicted_other_harm"]["H_action"] for item in group])
            ),
            "intervention_rate": float(
                np.mean([item["predicted_other_harm"]["intervene"] for item in group])
            ),
        }
    result = {
        "pairs": len(records),
        "context_until": args.context_until,
        "harm_scale_training_q95": scale,
        "aggregate_metrics": aggregate,
        "conditions": by_condition,
        "records": records,
    }
    save_metrics(result, output / "metrics.json")
    lines = [
        "# Stage 7 Self/Other Dissociation",
        "",
        "## Known objective facts",
        "",
        "| Condition | n | Actual Self H | Predicted Self-CF H | Actual Other H | Predicted Other H | Intervention rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *[
            f"| {name} | {item['n']} | {item['actual_self_H']:.4f} | {item['predicted_self_cf_H']:.4f} | {item['actual_other_H']:.4f} | {item['predicted_other_H']:.4f} | {item['intervention_rate']:.3f} |"
            for name, item in by_condition.items()
        ],
        "",
        "## Fact-based analysis",
        "",
        "Self-counterfactual, calibrated Other, Self-projection, shuffled-body-context, and time-shift errors are stored separately in `metrics.json`. A positive claim requires calibrated Other prediction to improve over Self-projection in mismatch conditions; otherwise the negative result is retained.",
        "",
    ]
    (output / "STAGE7_DISSOCIATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"pairs": len(records), "conditions": by_condition, "aggregate_metrics": aggregate}, indent=2))


def protection_run(args: argparse.Namespace) -> None:
    analysis = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    rows = {
        row["pair_id"]: row
        for row in load_manifest(args.manifest)
        if row["role"] == "other"
    }
    selected = {}
    for record in analysis["records"]:
        if record["condition"] in {"self_high_other_low", "self_low_other_high"}:
            selected.setdefault(record["condition"], record)
    results = []
    for condition, record in selected.items():
        row = rows[record["pair_id"]]
        metadata = json.loads((Path(row["path"]) / "metadata.json").read_text(encoding="utf-8"))
        before = metadata["summary"]
        intervene = bool(record["predicted_other_harm"]["intervene"])
        after = before
        if intervene:
            stopped = run_episode(
                EpisodeConfig(
                    episode_id=f"S8_{record['pair_id']}_stopped",
                    seed=metadata["seed"],
                    speed=metadata["speed"],
                    posture=metadata["posture"],
                    contact_location=metadata["contact_location"],
                    body_condition=metadata["body_condition"],
                    role="other",
                    pair_id=metadata["pair_id"],
                    self_body_condition=metadata["self_body_condition"],
                    dissociation_condition=condition,
                    stop_probe_at_s=args.stop_at,
                ),
                args.output,
            )
            after = stopped["summary"]
        results.append(
            {
                "condition": condition,
                "pair_id": record["pair_id"],
                "predicted_other_H": record["predicted_other_harm"]["H_action"],
                "predicted_other_intervene": intervene,
                "unprotected_peak_force_n": before["peak_contact_force_n"],
                "post_action_peak_force_n": after["peak_contact_force_n"],
                "force_reduction_n": before["peak_contact_force_n"]
                - after["peak_contact_force_n"],
            }
        )
    by_condition = {item["condition"]: item for item in results}
    gate = {
        "self_high_other_low_no_intervention": not by_condition.get(
            "self_high_other_low", {"predicted_other_intervene": True}
        )["predicted_other_intervene"],
        "self_low_other_high_intervention": by_condition.get(
            "self_low_other_high", {"predicted_other_intervene": False}
        )["predicted_other_intervene"],
        "intervention_reduces_force": by_condition.get(
            "self_low_other_high", {"force_reduction_n": 0.0}
        )["force_reduction_n"]
        > 0.0,
    }
    result = {"stop_at_s": args.stop_at, "gate": gate, "conditions": results}
    save_metrics(result, Path(args.output) / "metrics.json")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(8, 4), constrained_layout=True)
    axis.bar(
        [item["condition"] for item in results],
        [item["predicted_other_H"] for item in results],
        color=["tab:red" if item["predicted_other_intervene"] else "tab:gray" for item in results],
    )
    axis.axhline(0.75, color="black", linestyle="--", label="action threshold")
    axis.set_ylabel("Predicted Other H_action")
    axis.set_title(f"Protection decision; physical stop time = {args.stop_at:.2f} s")
    axis.tick_params(axis="x", rotation=15)
    axis.legend()
    figure.savefig(Path(args.output) / "protection_decision.png", dpi=150)
    plt.close(figure)
    print(json.dumps(result, indent=2))


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    subcommands = command.add_subparsers(dest="command", required=True)

    generate_parser = subcommands.add_parser("generate")
    generate_parser.add_argument("--design", choices=("self", "dissociation"), default="self")
    generate_parser.add_argument("--repetitions", type=int, default=20)
    generate_parser.add_argument("--seed", type=int, default=20260903)
    generate_parser.add_argument("--output", default=str(DEFAULT_DATA / "raw" / "self"))
    generate_parser.add_argument("--controls", action=argparse.BooleanOptionalAction, default=True)
    generate_parser.add_argument("--overwrite", action="store_true")
    generate_parser.set_defaults(function=generate)

    prepare_parser = subcommands.add_parser("prepare")
    prepare_parser.add_argument("--raw", default=str(DEFAULT_DATA / "raw" / "self"))
    prepare_parser.add_argument("--processed", default=str(DEFAULT_DATA / "processed" / "self"))
    prepare_parser.add_argument("--manifest", default=str(DEFAULT_DATA / "manifests" / "self.csv"))
    prepare_parser.add_argument("--normalization", default=str(DEFAULT_DATA / "manifests" / "self_normalization.json"))
    prepare_parser.add_argument("--steps", type=int, default=60)
    prepare_parser.add_argument("--image-size", type=int, default=16)
    prepare_parser.add_argument("--seed", type=int, default=20260903)
    prepare_parser.set_defaults(function=prepare)

    train_parser = subcommands.add_parser("train")
    train_parser.add_argument("--manifest", required=True)
    train_parser.add_argument("--normalization", required=True)
    train_parser.add_argument("--modalities", choices=("XP", "XT", "XTPI"), required=True)
    train_parser.add_argument("--role", choices=("self", "other", "all"), default="self")
    train_parser.add_argument(
        "--body-condition", choices=("all", "rigid", "compliant"), default="all"
    )
    train_parser.add_argument("--fraction", type=float, default=1.0)
    train_parser.add_argument("--output", required=True)
    train_parser.add_argument("--steps", type=int, default=1000)
    train_parser.add_argument("--learning-rate", type=float, default=1e-3)
    train_parser.add_argument("--obs-max", type=int, default=5)
    train_parser.add_argument("--validate-every", type=int, default=50)
    train_parser.add_argument("--patience", type=int, default=6)
    train_parser.add_argument("--latent-size", type=int, default=32)
    train_parser.add_argument("--hidden-size", type=int, default=64)
    train_parser.add_argument("--trunk-size", type=int, default=96)
    train_parser.add_argument("--nonvisual-weight", type=float, default=1.0)
    train_parser.add_argument("--seed", type=int, default=20260903)
    train_parser.set_defaults(function=train_model)

    evaluate_parser = subcommands.add_parser("evaluate")
    evaluate_parser.add_argument("--model", required=True)
    evaluate_parser.add_argument("--manifest", required=True)
    evaluate_parser.add_argument("--normalization", required=True)
    evaluate_parser.add_argument("--context", choices=("X", "P", "T", "XP", "XPI"), required=True)
    evaluate_parser.add_argument("--context-until", type=float, default=0.35)
    evaluate_parser.add_argument("--split", choices=("train", "validation", "test"), default="test")
    evaluate_parser.add_argument("--role", choices=("self", "other", "all"), default="self")
    evaluate_parser.add_argument(
        "--body-condition", choices=("all", "rigid", "compliant"), default="all"
    )
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.set_defaults(function=evaluate_model)

    physics_parser = subcommands.add_parser("physics-report")
    physics_parser.add_argument("--raw", required=True)
    physics_parser.add_argument("--output", default=str(HERE / "reports" / "STAGE2_PHYSICS_VALIDATION.md"))
    physics_parser.set_defaults(function=physics_report)

    harm_parser = subcommands.add_parser("harm-report")
    harm_parser.add_argument("--manifest", required=True)
    harm_parser.add_argument("--predictions", required=True)
    harm_parser.add_argument("--role", choices=("self", "other"), default="self")
    harm_parser.add_argument("--split", choices=("validation", "test"), default="test")
    harm_parser.add_argument("--output", required=True)
    harm_parser.set_defaults(function=harm_report)

    dissociation_parser = subcommands.add_parser("dissociation-report")
    dissociation_parser.add_argument("--manifest", required=True)
    dissociation_parser.add_argument("--normalization", required=True)
    dissociation_parser.add_argument("--self-rigid-model", required=True)
    dissociation_parser.add_argument("--self-compliant-model", required=True)
    dissociation_parser.add_argument("--other-rigid-model", required=True)
    dissociation_parser.add_argument("--other-compliant-model", required=True)
    dissociation_parser.add_argument("--context-until", type=float, default=0.35)
    dissociation_parser.add_argument("--split", choices=("validation", "test"), default="test")
    dissociation_parser.add_argument("--output", required=True)
    dissociation_parser.set_defaults(function=dissociation_report)

    protection_parser = subcommands.add_parser("protection-run")
    protection_parser.add_argument("--manifest", required=True)
    protection_parser.add_argument("--metrics", required=True)
    protection_parser.add_argument("--stop-at", type=float, default=0.7)
    protection_parser.add_argument("--output", required=True)
    protection_parser.set_defaults(function=protection_run)
    return command


def main() -> None:
    args = parser().parse_args()
    if getattr(args, "repetitions", 1) <= 0:
        raise ValueError("repetitions must be positive")
    if not 0.0 < getattr(args, "fraction", 1.0) <= 1.0:
        raise ValueError("fraction must be in (0,1]")
    if getattr(args, "nonvisual_weight", 1.0) <= 0.0:
        raise ValueError("nonvisual-weight must be positive")
    args.function(args)


if __name__ == "__main__":
    main()
