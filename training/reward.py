"""Reward functions compatible with VERL's compute_score interface.

VERL expects: compute_score(data_source, solution_str, ground_truth, extra_info) -> float
"""

from __future__ import annotations

import json
from typing import Any


def task_success_reward(
    data_source: str,
    solution_str: str,
    ground_truth: dict[str, Any],
    extra_info: dict[str, Any] | None = None,
) -> float:
    """Binary reward: 1.0 if the task was completed successfully, 0.0 otherwise."""
    extra_info = extra_info or {}
    success = extra_info.get("success", False)
    return 1.0 if success else 0.0


def efficiency_reward(
    data_source: str,
    solution_str: str,
    ground_truth: dict[str, Any],
    extra_info: dict[str, Any] | None = None,
) -> float:
    """Reward that penalizes extra steps beyond the optimal solution.

    Score = 1.0 - 0.1 * (actual_steps - optimal_steps), clamped to [0.1, 1.0].
    Only awarded if the task succeeded.
    """
    extra_info = extra_info or {}
    success = extra_info.get("success", False)
    if not success:
        return 0.0

    actual_steps = extra_info.get("total_steps", 0)
    optimal_steps = ground_truth.get("optimal_steps", 1)
    penalty = 0.1 * max(0, actual_steps - optimal_steps)
    return max(0.1, 1.0 - penalty)


def safety_reward(
    data_source: str,
    solution_str: str,
    ground_truth: dict[str, Any],
    extra_info: dict[str, Any] | None = None,
) -> float:
    """Penalty for safety violations: -1.0 if violated, 0.0 otherwise."""
    extra_info = extra_info or {}
    safety_violation = extra_info.get("safety_violation", False)
    return -1.0 if safety_violation else 0.0


def composite_reward(
    data_source: str,
    solution_str: str,
    ground_truth: dict[str, Any],
    extra_info: dict[str, Any] | None = None,
) -> float:
    """Weighted composite: 0.6*success + 0.3*efficiency + 0.1*safety.

    Safety reward is shifted to [0, 1] range for combination:
    safety_component = 0.0 if violation, 1.0 if no violation.
    """
    success_score = task_success_reward(data_source, solution_str, ground_truth, extra_info)
    eff_score = efficiency_reward(data_source, solution_str, ground_truth, extra_info)
    safe_score = safety_reward(data_source, solution_str, ground_truth, extra_info)

    # Normalize safety to [0, 1] for composition (0.0 = violation, 1.0 = clean)
    safe_normalized = 1.0 if safe_score >= 0.0 else 0.0

    return 0.6 * success_score + 0.3 * eff_score + 0.1 * safe_normalized


# Reward function registry
REWARD_FUNCTIONS = {
    "task_success": task_success_reward,
    "efficiency": efficiency_reward,
    "safety": safety_reward,
    "composite": composite_reward,
}


def compute_score(
    data_source: str,
    solution_str: str,
    ground_truth: dict[str, Any] | str,
    extra_info: dict[str, Any] | str | None = None,
) -> float:
    """VERL-compatible dispatch function.

    Routes to the appropriate reward function based on data_source.
    data_source format: "physical_ai_{reward_type}" or just the reward type name.

    Args:
        data_source: Identifier that determines which reward function to use.
        solution_str: The agent's full response/solution text.
        ground_truth: Expected outcome dict (or JSON string).
        extra_info: Additional trajectory metadata (or JSON string).

    Returns:
        Reward score as a float.
    """
    # Parse JSON strings if needed
    if isinstance(ground_truth, str):
        ground_truth = json.loads(ground_truth)
    if isinstance(extra_info, str):
        extra_info = json.loads(extra_info)
    extra_info = extra_info or {}

    # Determine reward function from data_source
    reward_type = data_source
    if reward_type.startswith("physical_ai_"):
        reward_type = reward_type[len("physical_ai_"):]

    fn = REWARD_FUNCTIONS.get(reward_type, composite_reward)
    return fn(data_source, solution_str, ground_truth, extra_info)
