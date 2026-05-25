#!/usr/bin/env python3
"""CLI script to export trajectories to VERL Parquet format.

Usage:
    python -m training.scripts.run_export --input ./data/trajectories --output ./data/parquet
    python -m training.scripts.run_export --input ./data/trajectories --reward-fn efficiency --split 0.8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from training.export_parquet import export_to_parquet
from training.reward import REWARD_FUNCTIONS


def main():
    parser = argparse.ArgumentParser(description="Export trajectories to VERL Parquet format")
    parser.add_argument("--input", required=True,
                        help="Directory containing trajectory .json files")
    parser.add_argument("--output", default="./data/parquet",
                        help="Output directory for parquet files (default: ./data/parquet)")
    parser.add_argument("--split", type=float, default=0.9,
                        help="Train/eval split ratio (default: 0.9)")
    parser.add_argument("--reward-fn", default="composite",
                        choices=list(REWARD_FUNCTIONS.keys()),
                        help="Reward function to use (default: composite)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for split (default: 42)")

    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"Error: Input directory does not exist: {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Export Configuration:")
    print(f"  Input: {input_dir}")
    print(f"  Output: {args.output}")
    print(f"  Split ratio: {args.split} train / {1 - args.split:.2f} eval")
    print(f"  Reward function: {args.reward_fn}")
    print()

    try:
        stats = export_to_parquet(
            input_dir=input_dir,
            output_dir=args.output,
            split_ratio=args.split,
            reward_fn_name=args.reward_fn,
            seed=args.seed,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"=== Export Summary ===")
    print(f"  Total trajectories: {stats['total_trajectories']}")
    print(f"  Train set: {stats['train_count']} samples -> {stats['train_path']}")
    print(f"  Eval set: {stats['eval_count']} samples -> {stats['eval_path']}")
    print(f"  Average reward: {stats['avg_reward']:.4f}")
    print(f"  Reward function: {stats['reward_fn']}")


if __name__ == "__main__":
    main()
