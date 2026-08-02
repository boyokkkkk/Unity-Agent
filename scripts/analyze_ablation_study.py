from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import fisher_exact

from scripts.collect_ablation_results import collect_ablation_results


LABELS = {
    1: "G1 Full",
    2: "G2 -Recovery",
    3: "G3 -Evidence artifact",
    4: "G4 -Dynamic tools",
    5: "G5 -Search budget",
    6: "G6 -Project graph",
    7: "G7 -Submission contract",
    8: "G8 -Typed mutations",
    9: "G9 -Validation gates",
}

OKABE_ITO = {
    "blue": "#0072B2",
    "sky": "#56B4E9",
    "green": "#009E73",
    "orange": "#E69F00",
    "vermillion": "#D55E00",
    "pink": "#CC79A7",
    "yellow": "#F0E442",
    "gray": "#999999",
}


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return math.nan, math.nan
    probability = successes / total
    denominator = 1 + z * z / total
    center = (probability + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        probability * (1 - probability) / total + z * z / (4 * total * total)
    ) / denominator
    return center - margin, center + margin


def holm_adjust(p_values: dict[int, float]) -> dict[int, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[int, float] = {}
    running_max = 0.0
    count = len(ordered)
    for rank, (group, p_value) in enumerate(ordered):
        candidate = min(1.0, (count - rank) * p_value)
        running_max = max(running_max, candidate)
        adjusted[group] = running_max
    return adjusted


def enrich_with_stage_metrics(df: pd.DataFrame, artifact_root: Path) -> pd.DataFrame:
    enriched = df.copy()
    rows: dict[str, dict[str, float | int | None]] = {}
    for run_id in enriched["run_id"]:
        path = artifact_root / run_id / "stage-metrics.json"
        metrics = json.loads(path.read_text(encoding="utf-8"))
        milestones = metrics.get("milestones_ms", {})
        navigation = metrics.get("navigation", {})
        context = metrics.get("context", {})
        end_ms = milestones.get("T9_hidden_validation_end")
        rows[run_id] = {
            "wall_minutes": (float(end_ms) / 60_000) if end_ms is not None else math.nan,
            "root_cause_rank": navigation.get("root_cause_rank"),
            "relevant_recall": navigation.get("relevant_recall"),
            "navigation_precision": navigation.get("navigation_precision"),
            "unrelated_file_ratio": navigation.get("unrelated_file_ratio"),
            "peak_context_usage_percent": context.get("peak_context_usage_percent"),
            "raw_output_chars": context.get("raw_output_chars"),
            "retained_output_chars": context.get("retained_output_chars"),
        }
    additions = pd.DataFrame.from_dict(rows, orient="index")
    additions.index.name = "run_id"
    return enriched.merge(additions.reset_index(), on="run_id", how="left")


def build_group_summary(df: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, float | int | str]] = []
    baseline = df[df["group"] == 1]
    baseline_successes = int(baseline["verified_success"].sum())
    baseline_failures = len(baseline) - baseline_successes
    raw_p_values: dict[int, float] = {}

    for group, group_df in df.groupby("group"):
        successes = int(group_df["verified_success"].sum())
        total = len(group_df)
        failures = total - successes
        if group != 1:
            raw_p_values[int(group)] = float(
                fisher_exact(
                    [[baseline_successes, baseline_failures], [successes, failures]],
                    alternative="two-sided",
                ).pvalue
            )

    adjusted = holm_adjust(raw_p_values)
    baseline_rate = baseline_successes / len(baseline)
    for group, group_df in df.groupby("group"):
        group = int(group)
        successes = int(group_df["verified_success"].sum())
        total = len(group_df)
        rate = successes / total
        ci_low, ci_high = wilson_interval(successes, total)
        records.append(
            {
                "group": group,
                "condition": LABELS[group],
                "runs": total,
                "successes": successes,
                "success_rate": rate,
                "success_ci_low": ci_low,
                "success_ci_high": ci_high,
                "delta_vs_full_pp": (rate - baseline_rate) * 100,
                "fisher_p_vs_full": raw_p_values.get(group, math.nan),
                "holm_p_vs_full": adjusted.get(group, math.nan),
                "tokens_mean": group_df["total_tokens"].mean(),
                "tokens_sd": group_df["total_tokens"].std(ddof=1),
                "tokens_median": group_df["total_tokens"].median(),
                "rounds_mean": group_df["rounds"].mean(),
                "wall_minutes_mean": group_df["wall_minutes"].mean(),
                "diagnose_rate": group_df["reached_diagnose"].mean(),
                "edit_rate": group_df["reached_edit"].mean(),
                "validate_rate": group_df["reached_validate"].mean(),
                "review_rate": group_df["reached_review"].mean(),
                "submit_rate": group_df["reached_submit"].mean(),
                "mutation_calls_mean": group_df["mutation_calls"].mean(),
                "typed_mutation_ratio_mean": group_df["typed_mutation_ratio"].mean(),
                "escape_hatch_ratio_mean": group_df["escape_hatch_ratio"].mean(),
                "protocol_completion_mean": group_df["protocol_gate_completion"].mean(),
                "format_errors_mean": group_df["format_errors"].mean(),
                "relevant_recall_mean": group_df["relevant_recall"].mean(),
                "navigation_precision_mean": group_df["navigation_precision"].mean(),
            }
        )
    return pd.DataFrame(records).sort_values("group")


def configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif"],
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.titleweight": "bold",
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "legend.frameon": False,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.18,
            "grid.linestyle": "-",
        }
    )
    sns.set_palette("colorblind")


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.pdf")
    fig.savefig(output_dir / f"{stem}.png", dpi=300)
    plt.close(fig)


def plot_primary(summary: pd.DataFrame, df: pd.DataFrame, output_dir: Path) -> None:
    groups = summary["group"].to_numpy()
    labels = [LABELS[int(group)] for group in groups]
    y = np.arange(len(groups))
    rates = summary["success_rate"].to_numpy() * 100
    low = summary["success_ci_low"].to_numpy() * 100
    high = summary["success_ci_high"].to_numpy() * 100
    colors = [OKABE_ITO["blue"]] + [OKABE_ITO["gray"]] * (len(groups) - 1)

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4), gridspec_kw={"wspace": 0.38})
    ax = axes[0]
    ax.barh(y, rates, color=colors, height=0.62, edgecolor="white")
    ax.errorbar(
        rates,
        y,
        xerr=np.vstack([rates - low, high - rates]),
        fmt="none",
        ecolor="#333333",
        capsize=3,
        linewidth=1,
    )
    for position, value in zip(y, rates):
        ax.text(min(value + 2, 103), position, f"{value:.0f}%", va="center", fontsize=8)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 112)
    ax.set_xlabel("Verified success rate (%)")
    ax.set_title("(a) Task success with Wilson 95% intervals")

    ax = axes[1]
    for group in groups:
        values = df.loc[df["group"] == group, "total_tokens"].to_numpy() / 1000
        x = np.full(len(values), group, dtype=float) + np.linspace(-0.12, 0.12, len(values))
        color = OKABE_ITO["blue"] if group == 1 else OKABE_ITO["gray"]
        ax.scatter(x, values, color=color, s=24, alpha=0.9, edgecolor="white", linewidth=0.4)
        ax.plot([group - 0.22, group + 0.22], [values.mean(), values.mean()], color="#222222", lw=1.5)
    ax.axhline(81.92, color=OKABE_ITO["vermillion"], linestyle="--", linewidth=1, label="81.92k limit")
    ax.set_xticks(groups, [f"G{group}" for group in groups])
    ax.set_ylabel("Total tokens (thousands)")
    ax.set_xlabel("Ablation group")
    ax.set_title("(b) Per-run token consumption")
    ax.legend(loc="lower left")
    save_figure(fig, output_dir, "fig_ablation_primary")


def plot_stages(summary: pd.DataFrame, output_dir: Path) -> None:
    columns = ["diagnose_rate", "edit_rate", "validate_rate", "review_rate", "submit_rate"]
    matrix = summary.set_index("condition")[columns] * 100
    matrix.columns = ["Diagnose", "Edit", "Validate", "Review", "Submit"]
    fig, ax = plt.subplots(figsize=(6.8, 4.1))
    sns.heatmap(
        matrix,
        annot=True,
        fmt=".0f",
        cmap=sns.light_palette(OKABE_ITO["blue"], as_cmap=True),
        vmin=0,
        vmax=100,
        linewidths=1.2,
        linecolor="white",
        cbar_kws={"label": "Runs reaching stage (%)", "shrink": 0.8},
        ax=ax,
    )
    ax.set_xlabel("Protocol stage")
    ax.set_ylabel("")
    ax.set_title("Protocol completion profile by ablation")
    save_figure(fig, output_dir, "fig_ablation_stage_heatmap")


def plot_failures(df: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    statuses = [
        "Submitted",
        "TotalTokenLimitExceeded",
        "RepeatedFormatError",
        "NoProgressExceeded",
    ]
    table = pd.crosstab(df["group"], df["exit_status"]).reindex(
        index=range(1, 10), columns=statuses, fill_value=0
    )
    colors = [
        OKABE_ITO["green"],
        OKABE_ITO["vermillion"],
        OKABE_ITO["pink"],
        OKABE_ITO["orange"],
    ]
    fig, ax = plt.subplots(figsize=(7.4, 3.5))
    bottom = np.zeros(len(table))
    x = np.arange(1, 10)
    for status, color in zip(statuses, colors):
        values = table[status].to_numpy()
        ax.bar(x, values, bottom=bottom, label=status, color=color, width=0.68, edgecolor="white")
        bottom += values
    ax.set_xticks(x, [f"G{group}" for group in x])
    ax.set_yticks(range(0, 6))
    ax.set_xlabel("Ablation group")
    ax.set_ylabel("Runs")
    ax.set_title("Exit-status composition (n=5 per group)")
    ax.legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.18))
    save_figure(fig, output_dir, "fig_ablation_failure_modes")
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the controlled ablation study")
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-runs", type=int, default=45)
    args = parser.parse_args()

    artifact_root = Path(args.artifact_root)
    output_dir = Path(args.output_dir)
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    df = collect_ablation_results(artifact_root)
    if len(df) != args.expected_runs:
        raise SystemExit(f"Expected {args.expected_runs} runs, got {len(df)}")
    df = enrich_with_stage_metrics(df, artifact_root)
    summary = build_group_summary(df)

    configure_plotting()
    plot_primary(summary, df, figure_dir)
    plot_stages(summary, figure_dir)
    exits = plot_failures(df, figure_dir)

    df.to_csv(output_dir / "ablation_run_level_enriched.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / "ablation_group_statistics.csv", index=False, encoding="utf-8-sig")
    exits.to_csv(output_dir / "ablation_exit_status_counts.csv", encoding="utf-8-sig")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
