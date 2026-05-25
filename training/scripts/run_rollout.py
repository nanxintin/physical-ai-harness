#!/usr/bin/env python3
"""CLI script to run rollout data generation.

Usage:
    python -m training.scripts.run_rollout --dry-run --tasks all --episodes 1
    python -m training.scripts.run_rollout --model-url http://localhost:8000/v1 --tasks robot_stand_up,robot_walk_forward_2m
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from training.tasks import get_tasks
from training.rollout import run_batch


def _create_adapter(backend: str):
    """Create the appropriate mock adapter for the given backend."""
    if backend in ("mujoco_mock", "mujoco"):
        from harness.adapters.mujoco_go1.mock_adapter import MockMuJoCoAdapter
        return MockMuJoCoAdapter()
    elif backend in ("sumo_mock", "sumo"):
        from harness.adapters.sumo.mock_adapter import MockSUMOAdapter
        return MockSUMOAdapter()
    elif backend in ("mock", "ai2thor_mock"):
        from harness.adapters.mock_adapter import MockAdapter
        return MockAdapter()
    else:
        raise ValueError(f"Unknown backend: {backend}. Use: mujoco_mock, sumo_mock, mock")


def _progress_callback(task_id: str, episode: int, trajectory):
    """Print progress during rollout."""
    status = "SUCCESS" if trajectory.success else "FAILED"
    print(f"  [{status}] {task_id} episode {episode + 1} "
          f"| steps={trajectory.total_steps} "
          f"| time={trajectory.total_time_ms:.0f}ms")


async def main():
    parser = argparse.ArgumentParser(description="Run rollout data generation")
    parser.add_argument("--backend", default="auto",
                        help="Mock adapter backend, or 'auto' to use each task's default (default: auto)")
    parser.add_argument("--model-url", default="http://localhost:8000/v1",
                        help="vLLM server URL (default: http://localhost:8000/v1)")
    parser.add_argument("--model-name", default="Qwen/Qwen3-8B",
                        help="Model name (default: Qwen/Qwen3-8B)")
    parser.add_argument("--episodes", type=int, default=5,
                        help="Episodes per task (default: 5)")
    parser.add_argument("--tasks", default="all",
                        help="Comma-separated task IDs or 'all' (default: all)")
    parser.add_argument("--output", default="./data/trajectories",
                        help="Output directory (default: ./data/trajectories)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use scripted responses (no LLM server needed)")
    parser.add_argument("--temperature", type=float, default=0.7,
                        help="Sampling temperature (default: 0.7)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")

    args = parser.parse_args()

    # Resolve tasks
    try:
        tasks = get_tasks(args.tasks)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Filter tasks to those matching the backend
    # For 'all' mode, we need adapters for each backend, so group by backend
    backend_tasks: dict[str, list] = {}
    for task in tasks:
        # Use the specified backend or the task's default
        effective_backend = args.backend if args.backend != "auto" else task.backend
        backend_tasks.setdefault(effective_backend, []).append(task)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Rollout Configuration:")
    print(f"  Mode: {'DRY RUN (scripted)' if args.dry_run else 'LLM (' + args.model_name + ')'}")
    print(f"  Backend: {args.backend}")
    print(f"  Tasks: {len(tasks)}")
    print(f"  Episodes per task: {args.episodes}")
    print(f"  Output: {output_dir}")
    print()

    all_trajectories = []
    start_time = time.time()

    for backend, btasks in backend_tasks.items():
        print(f"--- Backend: {backend} ({len(btasks)} tasks) ---")
        adapter = _create_adapter(backend)

        trajectories = await run_batch(
            tasks=btasks,
            adapter=adapter,
            episodes_per_task=args.episodes,
            model_url=args.model_url,
            model_name=args.model_name,
            temperature=args.temperature,
            dry_run=args.dry_run,
            progress_callback=_progress_callback,
        )
        all_trajectories.extend(trajectories)

    # Save trajectories
    for i, traj in enumerate(all_trajectories):
        filename = f"{traj.task_id}_ep{i:04d}.json"
        traj.save_json(output_dir / filename)

    elapsed = time.time() - start_time

    # Print summary
    success_count = sum(1 for t in all_trajectories if t.success)
    print()
    print(f"=== Rollout Summary ===")
    print(f"  Total trajectories: {len(all_trajectories)}")
    print(f"  Successful: {success_count}/{len(all_trajectories)} "
          f"({100 * success_count / max(1, len(all_trajectories)):.1f}%)")
    print(f"  Total time: {elapsed:.1f}s")
    print(f"  Saved to: {output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
