#!/usr/bin/env python3
"""CLI script to launch VERL GRPO training.

This is a thin wrapper that loads the VERL config and starts the training loop.
Requires verl to be installed separately.

Usage:
    python -m training.scripts.run_verl_train --config training/configs/verl_grpo.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description="Launch VERL GRPO training")
    parser.add_argument("--config", default="training/configs/verl_grpo.yaml",
                        help="Path to VERL config YAML (default: training/configs/verl_grpo.yaml)")

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    # Check if verl is installed
    try:
        import verl  # noqa: F401
    except ImportError:
        print("=" * 60)
        print("ERROR: verl is not installed.")
        print()
        print("To install verl for GRPO training:")
        print("  pip install verl")
        print()
        print("Or install from source:")
        print("  git clone https://github.com/volcengine/verl.git")
        print("  cd verl && pip install -e .")
        print()
        print("After installation, re-run this script with:")
        print(f"  python -m training.scripts.run_verl_train --config {args.config}")
        print("=" * 60)
        sys.exit(1)

    # Load config
    try:
        import yaml
    except ImportError:
        print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    print(f"VERL GRPO Training Configuration:")
    print(f"  Config: {config_path}")
    print(f"  Model: {config['model']['path']}")
    print(f"  Algorithm: {config['algorithm']['name']}")
    print(f"  Train data: {config['data']['train_files']}")
    print(f"  Eval data: {config['data']['val_files']}")
    print(f"  Epochs: {config['trainer']['total_epochs']}")
    print(f"  Batch size: {config['data']['train_batch_size']}")
    print(f"  KL coef: {config['algorithm']['kl_coef']}")
    print(f"  Generations: {config['algorithm']['num_generations']}")
    print()

    # Register custom reward function
    from training.reward import compute_score

    # Launch VERL training
    from verl.trainer import GRPOTrainer

    trainer = GRPOTrainer(
        config=config,
        reward_fn=compute_score,
    )

    print("Starting VERL GRPO training...")
    trainer.train()
    print("Training complete.")


if __name__ == "__main__":
    main()
