"""MVP-1 Experiment Runner: World Model Self-Evolution Demo.

Runs the full self-evolution loop with synthetic data (no GPU/simulator needed)
to validate the pipeline end-to-end.

Usage:
    python -m scripts.run_mvp1                    # Quick demo (3 cycles)
    python -m scripts.run_mvp1 --cycles 5         # Full demo
    python -m scripts.run_mvp1 --real             # With PyBullet (requires pybullet)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def run_synthetic_demo(n_cycles: int = 3, output_dir: str = "data/evolution_mvp1"):
    """Run evolution loop with synthetic data (no external deps needed)."""
    from training.evolution_loop import EvolutionConfig, SelfEvolutionLoop

    print("=" * 60)
    print("  RISE² MVP-1: Self-Evolution Demo (Synthetic Data)")
    print("=" * 60)
    print(f"  Cycles: {n_cycles}")
    print(f"  Output: {output_dir}")
    print()

    config = EvolutionConfig(
        state_dim=11,
        action_dim=16,
        contact_dim=4,
        hidden_dim=128,  # smaller for fast demo
        wm_n_layers=2,   # lighter model
        wm_epochs_per_cycle=10,
        explore_episodes_per_cycle=20,
        max_steps_per_episode=10,
        robot_type="franka",
        goals_per_cycle=3,
        use_llm=False,
        imagination_scenarios=20,
        output_dir=output_dir,
    )

    loop = SelfEvolutionLoop(config)
    start = time.time()
    metrics = loop.run(n_cycles)
    elapsed = time.time() - start

    # Print summary
    print("\n" + "=" * 60)
    print("  EVOLUTION SUMMARY")
    print("=" * 60)
    print(f"  Total time: {elapsed:.1f}s")
    print(f"  Cycles completed: {n_cycles}")
    print(f"  Final skill library size: {loop.skill_library.skill_count}")
    print(f"  Total transitions collected: {len(loop.all_transitions)}")
    print()
    print("  Skill Growth per Cycle:")
    for m in metrics:
        print(
            f"    Cycle {m.cycle}: "
            f"{m.skill_library_size} skills "
            f"(+{m.skills_promoted} promoted, "
            f"WM error={m.wm_eval_metrics.get('mean_state_error', 0):.4f})"
        )
    print()
    print("  Learned Skills:")
    for name in loop.skill_library.learned_skills:
        skill = loop.skill_library.learned_skills[name]
        print(f"    - {name} ({skill.source}, {len(skill.action_sequence)} steps)")
    print()
    print(f"  Report: {output_dir}/evolution_report.json")


def run_pybullet_demo(n_cycles: int = 3, output_dir: str = "data/evolution_pybullet"):
    """Run evolution loop with real PyBullet simulation."""
    import asyncio

    try:
        from harness.adapters.pybullet_arm.adapter import PyBulletArmAdapter
        from harness.events import EventBus
    except ImportError as e:
        print(f"Error: {e}")
        print("Install pybullet: pip install pybullet numpy Pillow")
        sys.exit(1)

    from training.evolution_loop import EvolutionConfig, SelfEvolutionLoop

    print("=" * 60)
    print("  RISE² MVP-1: Self-Evolution Demo (PyBullet)")
    print("=" * 60)

    # Initialize PyBullet adapter
    event_bus = EventBus()
    adapter = PyBulletArmAdapter(event_bus=event_bus, render_mode="DIRECT")

    async def _init():
        return await adapter.initialize("table_top")

    result = asyncio.run(_init())
    print(f"  PyBullet initialized: {result}")

    config = EvolutionConfig(
        state_dim=11,
        action_dim=16,
        contact_dim=4,
        hidden_dim=256,
        wm_n_layers=4,
        wm_epochs_per_cycle=30,
        explore_episodes_per_cycle=50,
        max_steps_per_episode=20,
        robot_type="franka",
        goals_per_cycle=3,
        use_llm=False,
        imagination_scenarios=30,
        real_validation_episodes=5,
        output_dir=output_dir,
    )

    loop = SelfEvolutionLoop(config)
    metrics = loop.run(n_cycles, adapter=adapter)

    # Cleanup
    asyncio.run(adapter.shutdown())

    print(f"\n  Final skill library: {loop.skill_library.skill_count} skills")
    print(f"  Report: {output_dir}/evolution_report.json")


def main():
    parser = argparse.ArgumentParser(description="RISE² MVP-1: Self-Evolution Experiment")
    parser.add_argument("--cycles", type=int, default=3, help="Number of evolution cycles")
    parser.add_argument("--real", action="store_true", help="Use PyBullet (requires pybullet)")
    parser.add_argument("--output", type=str, default=None, help="Output directory")
    args = parser.parse_args()

    if args.real:
        output = args.output or "data/evolution_pybullet"
        run_pybullet_demo(n_cycles=args.cycles, output_dir=output)
    else:
        output = args.output or "data/evolution_mvp1"
        run_synthetic_demo(n_cycles=args.cycles, output_dir=output)


if __name__ == "__main__":
    main()
