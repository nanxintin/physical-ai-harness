"""Export trajectory JSON files to VERL-compatible Parquet format.

Reads trajectory files, computes rewards, and outputs train/eval splits
in the schema expected by VERL's data pipeline.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from training.reward import REWARD_FUNCTIONS, composite_reward
from training.trajectory import Trajectory


def _format_prompt(trajectory: Trajectory) -> str:
    """Extract the prompt (system + user messages) from a trajectory."""
    parts = []
    for msg in trajectory.messages:
        if msg["role"] == "system":
            parts.append(f"[System]\n{msg['content']}")
        elif msg["role"] == "user":
            parts.append(f"[User]\n{msg['content']}")
            break  # Only include up to first user message as prompt
    return "\n\n".join(parts)


def _format_solution(trajectory: Trajectory) -> str:
    """Format the agent's full solution (tool calls + final response)."""
    parts = []
    for msg in trajectory.messages:
        if msg["role"] == "assistant":
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", tc)
                    name = fn.get("name", "unknown")
                    args = fn.get("arguments", "{}")
                    parts.append(f"[Tool Call] {name}({args})")
            elif msg.get("content"):
                parts.append(f"[Response] {msg['content']}")
    return "\n".join(parts)


def export_to_parquet(
    input_dir: str | Path,
    output_dir: str | Path,
    split_ratio: float = 0.9,
    reward_fn_name: str = "composite",
    seed: int = 42,
) -> dict[str, Any]:
    """Convert trajectory JSON files to VERL Parquet format.

    Args:
        input_dir: Directory containing trajectory .json files.
        output_dir: Output directory for parquet files.
        split_ratio: Fraction of data for training (rest is eval).
        reward_fn_name: Which reward function to use.
        seed: Random seed for train/eval split.

    Returns:
        Statistics dict with counts and average rewards.
    """
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("pandas is required for Parquet export. Install with: pip install pandas pyarrow")

    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get reward function
    reward_fn = REWARD_FUNCTIONS.get(reward_fn_name, composite_reward)

    # Load all trajectories
    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No .json files found in {input_dir}")

    records: list[dict[str, Any]] = []
    total_reward = 0.0

    for json_path in json_files:
        trajectory = Trajectory.load_json(json_path)

        # Compute reward
        solution_str = _format_solution(trajectory)
        extra_info = {
            "success": trajectory.success,
            "total_steps": trajectory.total_steps,
            "safety_violation": trajectory.metadata.get("safety_violation", False),
        }
        # Merge optimal_steps into ground_truth for efficiency reward
        ground_truth_with_optimal = dict(trajectory.ground_truth)
        ground_truth_with_optimal["optimal_steps"] = trajectory.metadata.get("optimal_steps", 1)

        reward = reward_fn(
            f"physical_ai_{reward_fn_name}",
            solution_str,
            ground_truth_with_optimal,
            extra_info,
        )
        total_reward += reward

        # Format as VERL schema
        record = {
            "data_source": f"physical_ai_{trajectory.task_type}",
            "prompt": _format_prompt(trajectory),
            "ability": trajectory.task_type,
            "reward_model": {
                "style": "rule",
                "ground_truth": json.dumps(ground_truth_with_optimal),
                "extra_info": json.dumps(extra_info),
            },
            "extra_info": json.dumps({
                "task_id": trajectory.task_id,
                "task_type": trajectory.task_type,
                "backend": trajectory.metadata.get("backend", ""),
                "total_steps": trajectory.total_steps,
                "total_time_ms": trajectory.total_time_ms,
                "success": trajectory.success,
                "reward": reward,
            }),
        }
        records.append(record)

    # Shuffle and split
    random.seed(seed)
    random.shuffle(records)

    split_idx = int(len(records) * split_ratio)
    train_records = records[:split_idx]
    eval_records = records[split_idx:]

    # Save as Parquet
    train_path = output_dir / "train.parquet"
    eval_path = output_dir / "eval.parquet"

    if train_records:
        df_train = pd.DataFrame(train_records)
        df_train.to_parquet(train_path, index=False)

    if eval_records:
        df_eval = pd.DataFrame(eval_records)
        df_eval.to_parquet(eval_path, index=False)

    avg_reward = total_reward / len(records) if records else 0.0

    stats = {
        "total_trajectories": len(records),
        "train_count": len(train_records),
        "eval_count": len(eval_records),
        "avg_reward": avg_reward,
        "reward_fn": reward_fn_name,
        "train_path": str(train_path),
        "eval_path": str(eval_path),
    }
    return stats
