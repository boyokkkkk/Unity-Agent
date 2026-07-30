from __future__ import annotations

import itertools
import math
import random
from typing import Any


def percentile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def bootstrap_mean_ci(
    values: list[float],
    *,
    confidence: float = 0.95,
    resamples: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    if not values:
        return {
            "estimate": 0.0,
            "lower": 0.0,
            "upper": 0.0,
            "confidence": confidence,
            "resamples": resamples,
            "n": 0,
        }
    generator = random.Random(seed)
    size = len(values)
    means = [
        sum(values[generator.randrange(size)] for _ in range(size)) / size
        for _ in range(resamples)
    ]
    alpha = (1.0 - confidence) / 2.0
    return {
        "estimate": sum(values) / size,
        "lower": percentile(means, alpha),
        "upper": percentile(means, 1.0 - alpha),
        "confidence": confidence,
        "resamples": resamples,
        "n": size,
        "method": "percentile_bootstrap",
        "seed": seed,
    }


def paired_permutation_test(left: list[float], right: list[float]) -> dict[str, Any]:
    if len(left) != len(right):
        raise ValueError("paired samples must have equal length")
    differences = [a - b for a, b in zip(left, right)]
    nonzero = [value for value in differences if abs(value) > 1e-15]
    observed = abs(sum(differences) / len(differences)) if differences else 0.0
    if not nonzero:
        p_value = 1.0
        permutations = 1
    elif len(nonzero) <= 20:
        extreme = 0
        permutations = 2 ** len(nonzero)
        for signs in itertools.product((-1.0, 1.0), repeat=len(nonzero)):
            permuted = abs(
                sum(sign * value for sign, value in zip(signs, nonzero))
                / len(differences)
            )
            if permuted + 1e-15 >= observed:
                extreme += 1
        p_value = extreme / permutations
    else:
        generator = random.Random(42)
        permutations = 100_000
        extreme = sum(
            abs(
                sum(
                    (-1.0 if generator.random() < 0.5 else 1.0) * value
                    for value in nonzero
                )
                / len(differences)
            )
            + 1e-15
            >= observed
            for _ in range(permutations)
        )
        p_value = (extreme + 1) / (permutations + 1)
    return {
        "mean_difference": (
            sum(differences) / len(differences) if differences else 0.0
        ),
        "wins": sum(value > 1e-15 for value in differences),
        "ties": sum(abs(value) <= 1e-15 for value in differences),
        "losses": sum(value < -1e-15 for value in differences),
        "p_value": p_value,
        "permutations": permutations,
        "method": "exact_paired_sign_permutation" if len(nonzero) <= 20 else "monte_carlo_paired_sign_permutation",
    }


def mcnemar_exact(left: list[bool], right: list[bool]) -> dict[str, Any]:
    if len(left) != len(right):
        raise ValueError("paired samples must have equal length")
    left_only = sum(a and not b for a, b in zip(left, right))
    right_only = sum(b and not a for a, b in zip(left, right))
    discordant = left_only + right_only
    if discordant == 0:
        p_value = 1.0
    else:
        lower = min(left_only, right_only)
        tail = sum(
            math.comb(discordant, value)
            for value in range(lower + 1)
        ) / (2 ** discordant)
        p_value = min(1.0, 2.0 * tail)
    return {
        "left_only": left_only,
        "right_only": right_only,
        "discordant": discordant,
        "p_value": p_value,
        "method": "exact_mcnemar_binomial",
    }


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        corrected = min(1.0, value * (count - index))
        running = max(running, corrected)
        adjusted[name] = running
    return adjusted


def infer_localization_statistics(
    rows: list[dict[str, Any]],
    *,
    confidence: float = 0.95,
    resamples: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    metrics = sorted({
        key for row in rows for key in row.get("metrics", {})
    })
    variants = sorted({str(row["variant"]) for row in rows})
    by_variant = {
        variant: {
            str(row["task_id"]): row
            for row in rows if row["variant"] == variant
        }
        for variant in variants
    }
    bootstrap = {
        variant: {
            metric: bootstrap_mean_ci(
                [float(row["metrics"][metric]) for row in tasks.values()],
                confidence=confidence,
                resamples=resamples,
                seed=seed + metric_index,
            )
            for metric_index, metric in enumerate(metrics)
        }
        for variant, tasks in by_variant.items()
    }
    comparisons: dict[str, Any] = {}
    for left_variant, right_variant in (("A2", "A0"), ("A2", "A1")):
        common = sorted(set(by_variant.get(left_variant, {})) & set(by_variant.get(right_variant, {})))
        metric_tests: dict[str, Any] = {}
        permutation_p: dict[str, float] = {}
        mcnemar_p: dict[str, float] = {}
        for metric in metrics:
            left = [
                float(by_variant[left_variant][task]["metrics"][metric])
                for task in common
            ]
            right = [
                float(by_variant[right_variant][task]["metrics"][metric])
                for task in common
            ]
            permutation = paired_permutation_test(left, right)
            mcnemar = mcnemar_exact(
                [value >= 1.0 - 1e-15 for value in left],
                [value >= 1.0 - 1e-15 for value in right],
            )
            permutation_p[metric] = float(permutation["p_value"])
            mcnemar_p[metric] = float(mcnemar["p_value"])
            metric_tests[metric] = {
                "paired_permutation": permutation,
                "mcnemar_full_recall": mcnemar,
            }
        permutation_holm = holm_adjust(permutation_p)
        mcnemar_holm = holm_adjust(mcnemar_p)
        for metric in metrics:
            metric_tests[metric]["paired_permutation"]["holm_p_value"] = permutation_holm[metric]
            metric_tests[metric]["mcnemar_full_recall"]["holm_p_value"] = mcnemar_holm[metric]
        comparisons[f"{left_variant}_vs_{right_variant}"] = {
            "paired_tasks": common,
            "metrics": metric_tests,
        }
    return {
        "confidence_intervals": bootstrap,
        "paired_tests": comparisons,
        "notes": {
            "unit": "task",
            "bootstrap": "percentile bootstrap over tasks",
            "paired_permutation": "two-sided sign permutation of task-level paired differences",
            "mcnemar": "two-sided exact McNemar test on full-recall success",
            "multiplicity": "Holm correction within each comparison and test family",
        },
    }
