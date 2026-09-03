"""Regenerate the figures embedded in DETAILED_EXPERIMENT_REPORT.md."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "reports" / "figures"
OUTPUTS = HERE / "outputs"
CHECKPOINTS = HERE / "checkpoints"
RAW = HERE / "data" / "raw"

COLORS = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "red": "#D55E00",
    "purple": "#CC79A7",
    "gray": "#666666",
    "light": "#E6E6E6",
}

JP_FONT_PATH = next(
    (path for path in (Path("/System/Library/Fonts/Hiragino Sans GB.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")) if path.exists()),
    None,
)
JP_FONT = FontProperties(fname=str(JP_FONT_PATH)) if JP_FONT_PATH else FontProperties(family="sans-serif")
JP_BOLD = FontProperties(fname=str(JP_FONT_PATH), weight="bold") if JP_FONT_PATH else FontProperties(family="sans-serif", weight="bold")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(figure: plt.Figure, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURES / name, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def study_design() -> None:
    figure, axis = plt.subplots(figsize=(13, 5.8))
    axis.set_xlim(0, 13)
    axis.set_ylim(0, 6)
    axis.axis("off")
    boxes = (
        (0.3, 3.8, 2.4, 1.25, "Self physical experience\nX/T/P/I measured", COLORS["blue"]),
        (3.3, 3.8, 2.4, 1.25, "Self DMBN\ntimed observation/query", COLORS["blue"]),
        (6.3, 3.8, 2.4, 1.25, "Observe Other event\nX_other", COLORS["orange"]),
        (9.7, 4.35, 2.7, 1.25, "Self counterfactual\nT/P/I_self_cf", COLORS["orange"]),
        (9.7, 2.25, 2.7, 1.25, "Other-specific model\n+ body calibration", COLORS["green"]),
        (6.3, 0.55, 2.4, 1.25, "Other actual sensors\nT/P/I_other", COLORS["green"]),
        (9.7, 0.55, 2.7, 1.25, "Other-state prediction\n+ protection decision", COLORS["red"]),
    )
    for x, y, width, height, label, color in boxes:
        axis.add_patch(
            FancyBboxPatch(
                (x, y),
                width,
                height,
                boxstyle="round,pad=0.08,rounding_size=0.08",
                linewidth=1.8,
                edgecolor=color,
                facecolor="white",
            )
        )
        axis.text(x + width / 2, y + height / 2, label, ha="center", va="center", fontsize=11)
    arrows = (
        ((2.7, 4.43), (3.3, 4.43), COLORS["blue"]),
        ((5.7, 4.43), (6.3, 4.43), COLORS["blue"]),
        ((8.7, 4.43), (9.7, 4.95), COLORS["orange"]),
        ((8.7, 4.25), (9.7, 2.88), COLORS["green"]),
        ((7.5, 3.8), (7.5, 1.8), COLORS["green"]),
        ((8.7, 1.18), (9.7, 1.18), COLORS["green"]),
        ((11.05, 2.25), (11.05, 1.8), COLORS["red"]),
    )
    for start, end, color in arrows:
        axis.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=14, color=color, linewidth=1.8))
    axis.text(
        9.0,
        3.75,
        "Keep predictions separate",
        fontsize=9,
        color=COLORS["gray"],
        ha="center",
    )
    axis.set_title("Physical Self-to-Other DMBN study design", fontsize=15, weight="bold", pad=8)
    save(figure, "01_study_design.png")


def study_design_ja() -> None:
    figure, axis = plt.subplots(figsize=(16, 9))
    axis.set_xlim(0, 16)
    axis.set_ylim(0, 9)
    axis.axis("off")

    def box(
        x: float,
        y: float,
        width: float,
        height: float,
        title: str,
        body: str,
        color: str,
        dashed: bool = False,
        body_fraction: float = 0.43,
        body_size: float = 11.5,
    ) -> None:
        axis.add_patch(
            FancyBboxPatch(
                (x, y),
                width,
                height,
                boxstyle="round,pad=0.08,rounding_size=0.10",
                linewidth=2.2,
                linestyle="--" if dashed else "-",
                edgecolor=color,
                facecolor="white",
            )
        )
        axis.text(x + 0.18, y + height - 0.28, title, ha="left", va="top", fontsize=14, color=color, fontproperties=JP_BOLD)
        axis.text(x + width / 2, y + height * body_fraction, body, ha="center", va="center", fontsize=body_size, color="#25323b", fontproperties=JP_FONT, linespacing=1.45)

    def arrow(start: tuple[float, float], end: tuple[float, float], color: str = "#52616b") -> None:
        axis.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=16, color=color, linewidth=2.0, connectionstyle="arc3,rad=0"))

    axis.text(8, 8.55, "Self経験からOther状態推定・保護まで", ha="center", va="center", fontsize=23, color="#123047", fontproperties=JP_BOLD)
    axis.text(8, 8.14, "Self反実仮想とOther実状態予測を混ぜず、それぞれ対応する実測値で評価する", ha="center", va="center", fontsize=12.5, color="#52616b", fontproperties=JP_FONT)

    box(0.35, 6.15, 3.45, 1.55, "① Self実経験", "ロボットAが接触を受ける\nX：視覚　T：触覚\nP：固有受容　I：内部機械状態", COLORS["blue"])
    box(4.25, 6.15, 3.45, 1.55, "② Self身体モデル", "DMBNで時間関係を学習\n観測集合 ＋ 独立した時刻query\n予測を次時刻へ再入力しない", COLORS["blue"])
    box(8.15, 6.15, 3.8, 1.55, "③ Otherを観察", "Aの左眼でBへの接触を見る\nモデルへの主要入力：X_other\n同じ外的イベントを観測", COLORS["orange"])
    arrow((3.8, 6.93), (4.25, 6.93), COLORS["blue"])
    arrow((7.7, 6.93), (8.15, 6.93), COLORS["blue"])

    box(2.0, 3.55, 5.35, 1.75, "④-A Self反実仮想", "「同じ出来事がAに起きたら？」\n予測：T/P/I_self_cf\nA自身の身体モデルで内部シミュレーション", COLORS["orange"])
    box(8.65, 3.55, 5.35, 1.75, "④-B Other実状態予測", "「Bには実際に何が起きる？」\nX_other ＋ Bの身体情報／較正\n予測：T/P/I_other_hat", COLORS["green"])
    arrow((9.65, 6.15), (5.8, 5.3), COLORS["orange"])
    arrow((10.3, 6.15), (11.25, 5.3), COLORS["green"])

    box(2.0, 2.35, 5.35, 0.80, "評価用Self actual", "同一probe軌道でAを刺激した実測 T/P/I", "#66717a", dashed=True, body_fraction=0.18, body_size=10.5)
    box(8.65, 2.35, 5.35, 0.80, "評価用Other actual", "Bの実センサで測定した T/P/I", "#66717a", dashed=True, body_fraction=0.18, body_size=10.5)
    arrow((4.68, 3.55), (4.68, 3.15), "#66717a")
    arrow((11.32, 3.55), (11.32, 3.15), "#66717a")

    box(0.35, 0.55, 3.55, 1.25, "中心的な反証条件", "Self高／Other低\nSelf低／Other高", COLORS["red"])
    box(4.65, 0.55, 6.05, 1.25, "⑤ Self/Other解離を評価", "H_self_cf と H_other を別々に算出\nΔforce・Δload・軌道差を比較", COLORS["purple"])
    box(11.45, 0.55, 4.2, 1.25, "⑥ Other保護", "予測H_other ≥ 閾値 → probe停止\n低ければ介入しない", COLORS["red"])
    arrow((3.9, 1.18), (4.65, 1.18), COLORS["red"])
    arrow((7.35, 2.35), (7.35, 1.8), COLORS["purple"])
    arrow((8.65, 2.35), (8.15, 1.8), COLORS["purple"])
    arrow((10.7, 1.18), (11.45, 1.18), COLORS["red"])

    axis.text(15.65, 8.15, "実線：予測経路\n破線枠：評価用の実測値", ha="right", va="top", fontsize=9.5, color="#66717a", fontproperties=JP_FONT, linespacing=1.45)
    save(figure, "01_study_design_ja.png")


def physics_distributions() -> None:
    rows = []
    for path in sorted((RAW / "self_full").glob("*/metadata.json")):
        item = load_json(path)
        if item["role"] == "self" and not item["no_contact"]:
            rows.append({**item, **item["summary"]})
    panels = (
        ("speed", "peak_contact_force_n", ("slow", "medium", "fast"), "Peak contact force [N]"),
        ("speed", "contact_impulse_ns", ("slow", "medium", "fast"), "Contact impulse [N s]"),
        ("posture", "peak_joint_torque_nm", ("flexed", "neutral", "extended"), "Peak joint torque [N m]"),
        (
            "posture",
            "accumulated_torque_load_nms",
            ("flexed", "neutral", "extended"),
            "Accumulated torque load [N m s]",
        ),
    )
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    rng = np.random.default_rng(7)
    for axis, (factor, outcome, labels, ylabel) in zip(axes.flat, panels):
        groups = [[row[outcome] for row in rows if row[factor] == label] for label in labels]
        axis.boxplot(groups, tick_labels=labels, widths=0.55, showfliers=False)
        for index, values in enumerate(groups, 1):
            axis.scatter(
                index + rng.uniform(-0.10, 0.10, len(values)),
                values,
                s=9,
                alpha=0.28,
                color=COLORS["blue"],
                edgecolors="none",
            )
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", alpha=0.25)
        axis.text(0.02, 0.96, f"n={len(groups[0])} per level", transform=axis.transAxes, va="top", fontsize=9)
    figure.suptitle("Stage 2: physical outcome distributions", fontsize=15, weight="bold")
    save(figure, "02_physics_distributions.png")


def training_history() -> None:
    runs = (
        ("S3A_DMBN_XP_full", "X + P"),
        ("S3B_DMBN_XT_full", "X + T"),
        ("S3C_DMBN_XTPI_full", "X + T + P + I"),
    )
    figure, axes = plt.subplots(1, 3, figsize=(14, 4.2), constrained_layout=True)
    for axis, (directory, title) in zip(axes, runs):
        history = load_json(CHECKPOINTS / directory / "training_history.json")
        steps = np.asarray([item["step"] for item in history])
        train = np.asarray([item["train_nll"] for item in history])
        validation = np.asarray([item["validation_nll"] for item in history])
        axis.plot(steps, train, color=COLORS["blue"], alpha=0.65, label="training objective")
        axis.plot(steps, validation, color=COLORS["orange"], linewidth=2, label="validation objective")
        best = int(np.nanargmin(validation))
        axis.scatter(steps[best], validation[best], color=COLORS["red"], zorder=3, label="selected checkpoint")
        axis.set_yscale("symlog", linthresh=1.0)
        axis.set_title(title)
        axis.set_xlabel("Update step")
        axis.set_ylabel("NLL + normalized mean MSE")
        axis.grid(alpha=0.25)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    figure.suptitle("Validation-selected DMBN training histories", fontsize=15, weight="bold")
    save(figure, "03_training_history.png")


def self_model_comparison() -> None:
    sources = (
        ("S3A X→P", OUTPUTS / "S3A_DMBN_XP_full_X" / "metrics.json", "P"),
        ("S3B X→T", OUTPUTS / "S3B_DMBN_XT_full_X" / "metrics.json", "T"),
        ("S3C X→T", OUTPUTS / "S3C_DMBN_XTPI_full_X" / "metrics.json", "T"),
        ("S3C X→P", OUTPUTS / "S3C_DMBN_XTPI_full_X" / "metrics.json", "P"),
        ("S3C X→I", OUTPUTS / "S3C_DMBN_XTPI_full_X" / "metrics.json", "I"),
        ("S3C XPI→T", OUTPUTS / "S3C_DMBN_XTPI_full_XPI" / "metrics.json", "T"),
        ("S3C XPI→P", OUTPUTS / "S3C_DMBN_XTPI_full_XPI" / "metrics.json", "P"),
        ("S3C XPI→I", OUTPUTS / "S3C_DMBN_XTPI_full_XPI" / "metrics.json", "I"),
    )
    labels, ratios = [], []
    for label, path, modality in sources:
        metrics = load_json(path)
        labels.append(label)
        ratios.append(metrics["metrics"][modality]["mae"] / metrics["mean_baseline"][modality]["mae"])
    figure, axis = plt.subplots(figsize=(11, 5.2), constrained_layout=True)
    positions = np.arange(len(labels))
    colors = [COLORS["green"] if ratio < 1 else COLORS["red"] for ratio in ratios]
    bars = axis.bar(positions, ratios, color=colors)
    axis.axhline(1.0, color="black", linestyle="--", linewidth=1.3, label="unconditional mean")
    axis.set_xticks(positions, labels, rotation=30, ha="right")
    axis.set_ylabel("DMBN MAE / mean-trajectory MAE")
    axis.set_title("Stages 3A–3C: held-out error relative to the mean baseline", weight="bold")
    axis.grid(axis="y", alpha=0.25)
    axis.bar_label(bars, labels=[f"{value:.2f}×" for value in ratios], padding=3, fontsize=9)
    axis.legend(frameon=False)
    save(figure, "04_self_model_vs_baseline.png")


def calibration_curves() -> None:
    paths = {
        ("rigid", 7.14): OUTPUTS / "S6_CAL_005_rigid" / "metrics.json",
        ("rigid", 21.43): OUTPUTS / "S6_CAL_020_rigid" / "metrics.json",
        ("rigid", 100.0): OUTPUTS / "S6_CAL_100_rigid" / "metrics.json",
        ("compliant", 7.14): OUTPUTS / "S6_CAL_005_compliant" / "metrics.json",
        ("compliant", 21.43): OUTPUTS / "S6_CAL_020_compliant" / "metrics.json",
        ("compliant", 100.0): OUTPUTS / "S6_CAL_100_compliant" / "metrics.json",
    }
    zero = load_json(OUTPUTS / "S6_CAL_000_self_projection" / "metrics.json")
    figure, axes = plt.subplots(1, 3, figsize=(14, 4.4), constrained_layout=True)
    for axis, modality in zip(axes, ("T", "P", "I")):
        for body, color in (("rigid", COLORS["blue"]), ("compliant", COLORS["orange"])):
            xs = [0.0, 7.14, 21.43, 100.0]
            ys = [zero["metrics"][modality]["mae"]] + [
                load_json(paths[(body, fraction)])["metrics"][modality]["mae"]
                for fraction in xs[1:]
            ]
            axis.plot(xs, ys, marker="o", linewidth=2, color=color, label=body.capitalize())
        axis.set_title(f"{modality} trajectory")
        axis.set_xlabel("Realized Other calibration [%]")
        axis.set_ylabel("Held-out MAE")
        axis.set_yscale("log")
        axis.grid(alpha=0.25)
    axes[0].legend(frameon=False)
    figure.suptitle("Stage 6: calibration amount is not monotonically beneficial", fontsize=15, weight="bold")
    save(figure, "05_other_calibration.png")


def dissociation_summary() -> None:
    metrics = load_json(OUTPUTS / "S7_DISSOCIATION_full" / "metrics.json")
    order = ("matched_high", "self_high_other_low", "self_low_other_high", "matched_low")
    labels = ("Matched\nhigh", "Self high /\nOther low", "Self low /\nOther high", "Matched\nlow")
    keys = (
        ("actual_self_H", "Actual Self", COLORS["blue"]),
        ("predicted_self_cf_H", "Predicted Self-CF", COLORS["orange"]),
        ("actual_other_H", "Actual Other", COLORS["gray"]),
        ("predicted_other_H", "Predicted Other", COLORS["green"]),
    )
    figure, axis = plt.subplots(figsize=(12, 5.4), constrained_layout=True)
    x = np.arange(len(order))
    width = 0.19
    for index, (key, label, color) in enumerate(keys):
        axis.bar(x + (index - 1.5) * width, [metrics["conditions"][name][key] for name in order], width, label=label, color=color)
    axis.axhline(0.75, color=COLORS["red"], linestyle="--", linewidth=1.5, label="action threshold")
    axis.set_xticks(x, labels)
    axis.set_ylabel("Transparent harm readout H_action")
    axis.set_title("Stage 7: Self-counterfactual and Other-state dissociation", weight="bold")
    axis.grid(axis="y", alpha=0.25)
    axis.legend(ncol=3, frameon=False)
    save(figure, "06_dissociation_harm.png")


def control_comparison() -> None:
    metrics = load_json(OUTPUTS / "S7_DISSOCIATION_full" / "metrics.json")["aggregate_metrics"]
    methods = (
        ("self_projection", "Self projection", COLORS["orange"]),
        ("other", "Other-specific", COLORS["green"]),
        ("shuffled_body_context", "Shuffled body context", COLORS["red"]),
        ("time_shift", "Time-shifted X", COLORS["purple"]),
    )
    figure, axes = plt.subplots(1, 3, figsize=(14, 4.4), constrained_layout=True)
    for axis, modality in zip(axes, ("T", "P", "I")):
        reference = metrics["self_projection"][modality]["mae"]
        values = [metrics[name][modality]["mae"] / reference for name, _, _ in methods]
        bars = axis.bar(range(len(methods)), values, color=[color for _, _, color in methods])
        axis.axhline(1.0, color="black", linestyle="--", linewidth=1.2)
        axis.set_xticks(range(len(methods)), [label for _, label, _ in methods], rotation=28, ha="right")
        axis.set_title(modality)
        axis.set_ylabel("MAE / Self-projection MAE")
        axis.grid(axis="y", alpha=0.25)
        axis.bar_label(bars, labels=[f"{value:.2f}×" for value in values], padding=2, fontsize=8)
    figure.suptitle("Stage 7 controls: body context matters, early timestamp shift does not", fontsize=15, weight="bold")
    save(figure, "07_dissociation_controls.png")


def mismatch_trajectory(condition: str, output_name: str) -> None:
    path = sorted((OUTPUTS / "S7_DISSOCIATION_full" / "predictions").glob(f"S7_{condition}_*.npz"))[0]
    with np.load(path, allow_pickle=False) as loaded:
        data = {name: loaded[name] for name in loaded.files}
    series = (
        ("T", 1, "Contact force [N]"),
        ("P", 3, "Elbow position [rad]"),
        ("I", 3, "Elbow torque [N m]"),
    )
    curves = (
        ("self_actual", "Actual Self", COLORS["blue"], ":"),
        ("self_cf", "Predicted Self-CF", COLORS["orange"], "--"),
        ("other_actual", "Actual Other", "black", "-"),
        ("other_predicted", "Predicted Other", COLORS["green"], "-."),
    )
    figure, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, constrained_layout=True)
    for axis, (modality, index, ylabel) in zip(axes, series):
        for prefix, label, color, linestyle in curves:
            values = data[f"{prefix}_{modality}"][:, index]
            if modality == "P":
                values = (values - values[0]) * 1000.0
                ylabel = "Elbow position change [mrad]"
            axis.plot(data["time_s"], values, label=label, color=color, linestyle=linestyle, linewidth=1.8)
        axis.set_ylabel(ylabel)
        axis.grid(alpha=0.25)
    axes[-1].set_xlabel("Time [s]")
    axes[0].legend(ncol=2, frameon=False)
    figure.suptitle(condition.replace("_", " ").title(), fontsize=15, weight="bold")
    save(figure, output_name)


def protection_result() -> None:
    stage7 = load_json(OUTPUTS / "S7_DISSOCIATION_full" / "metrics.json")["conditions"]
    stage8 = load_json(OUTPUTS / "S8_OTHER_PROTECTION_full" / "metrics.json")
    order = ("self_high_other_low", "self_low_other_high")
    labels = ("Self high /\nOther low", "Self low /\nOther high")
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    x = np.arange(2)
    width = 0.34
    axes[0].bar(x - width / 2, [stage7[name]["actual_other_H"] for name in order], width, label="Actual Other", color=COLORS["gray"])
    axes[0].bar(x + width / 2, [stage7[name]["predicted_other_H"] for name in order], width, label="Predicted Other", color=COLORS["green"])
    axes[0].axhline(0.75, color=COLORS["red"], linestyle="--", label="threshold")
    axes[0].set_xticks(x, labels)
    axes[0].set_ylabel("H_action")
    axes[0].set_title("Decision input")
    axes[0].legend(frameon=False)
    by_condition = {item["condition"]: item for item in stage8["conditions"]}
    axes[1].bar(x - width / 2, [by_condition[name]["unprotected_peak_force_n"] for name in order], width, label="Unprotected", color=COLORS["red"])
    axes[1].bar(x + width / 2, [by_condition[name]["post_action_peak_force_n"] for name in order], width, label="After policy", color=COLORS["blue"])
    axes[1].set_xticks(x, labels)
    axes[1].set_ylabel("Peak contact force [N]")
    axes[1].set_title("Executed physical outcome")
    axes[1].legend(frameon=False)
    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle("Stage 8: high-Other underestimation prevents intervention", fontsize=15, weight="bold")
    save(figure, "10_protection_result.png")


def main() -> None:
    study_design()
    study_design_ja()
    physics_distributions()
    training_history()
    self_model_comparison()
    calibration_curves()
    dissociation_summary()
    control_comparison()
    mismatch_trajectory("self_high_other_low", "08_self_high_other_low_trajectory.png")
    mismatch_trajectory("self_low_other_high", "09_self_low_other_high_trajectory.png")
    protection_result()
    expected = {"01_study_design.png", "01_study_design_ja.png"} | {
        f"{index:02d}_{name}.png"
        for index, name in (
            (2, "physics_distributions"),
            (3, "training_history"),
            (4, "self_model_vs_baseline"),
            (5, "other_calibration"),
            (6, "dissociation_harm"),
            (7, "dissociation_controls"),
            (8, "self_high_other_low_trajectory"),
            (9, "self_low_other_high_trajectory"),
            (10, "protection_result"),
        )
    }
    produced = {path.name for path in FIGURES.glob("*.png")}
    assert expected <= produced, f"Missing figures: {expected - produced}"
    print(f"generated {len(list(FIGURES.glob('*.png')))} report figures in {FIGURES}")


if __name__ == "__main__":
    main()
