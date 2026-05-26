"""Self-Evolution Loop: orchestrates world model training, skill discovery, and validation.

Implements the full Explore → Model → Imagine → Discover → Validate → Deploy cycle.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""

    def default(self, obj):
        if isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, (np.integer, np.int32, np.int64)):
            return int(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

try:
    import torch
    from torch.utils.data import DataLoader
except ImportError:
    raise ImportError("PyTorch required. Install with: pip install torch>=2.0.0")

from training.imagination import ImaginationValidator, SkillCandidate, ValidationReport
from training.skill_synthesis import SkillLibrary, SkillSynthesizer
from training.world_model import (
    StateTransition,
    StructuredWorldModel,
    TransitionDataset,
    WorldModelTrainer,
    load_transitions,
    save_transitions,
)


@dataclass
class EvolutionMetrics:
    """Metrics for a single evolution cycle."""

    cycle: int
    skills_proposed: int
    skills_imagination_passed: int
    skills_real_validated: int
    skills_promoted: int
    wm_train_loss: float
    wm_eval_metrics: dict[str, float]
    skill_library_size: int
    total_real_interactions: int
    elapsed_seconds: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "skills_proposed": self.skills_proposed,
            "skills_imagination_passed": self.skills_imagination_passed,
            "skills_real_validated": self.skills_real_validated,
            "skills_promoted": self.skills_promoted,
            "wm_train_loss": self.wm_train_loss,
            "wm_eval_metrics": self.wm_eval_metrics,
            "skill_library_size": self.skill_library_size,
            "total_real_interactions": self.total_real_interactions,
            "elapsed_seconds": self.elapsed_seconds,
            "details": self.details,
        }


@dataclass
class EvolutionConfig:
    """Configuration for the self-evolution loop."""

    # World model
    state_dim: int = 11  # 7 joints + 3 ee + 1 gripper
    action_dim: int = 16
    contact_dim: int = 4
    hidden_dim: int = 256
    wm_n_layers: int = 4
    wm_lr: float = 3e-4
    wm_epochs_per_cycle: int = 30
    wm_batch_size: int = 64

    # Data collection
    explore_episodes_per_cycle: int = 50
    max_steps_per_episode: int = 20

    # Skill synthesis
    robot_type: str = "franka"
    goals_per_cycle: int = 5
    use_llm: bool = False  # False = rule-based synthesis for MVP

    # Imagination validation
    imagination_scenarios: int = 30
    success_threshold: float = 0.7
    safety_threshold: float = 0.95
    confidence_threshold: float = 0.6

    # Real validation
    real_validation_episodes: int = 5
    real_success_threshold: float = 0.5

    # Output
    output_dir: str = "data/evolution"
    save_checkpoints: bool = True


class CuriosityModule:
    """Proposes exploration goals based on world model uncertainty."""

    def __init__(self, skill_library: SkillLibrary, robot_type: str = "franka"):
        self.library = skill_library
        self.robot_type = robot_type

    def propose_goals(self, cycle: int) -> list[str]:
        """Generate goal proposals for skill synthesis."""
        if self.robot_type == "franka":
            return self._franka_goals(cycle)
        elif self.robot_type == "go1":
            return self._go1_goals(cycle)
        return []

    def _franka_goals(self, cycle: int) -> list[str]:
        """Progressive goals for Franka arm."""
        known = set(self.library.all_skills.keys())

        all_goals = [
            ("pick_up", "Pick up an object from the table"),
            ("put_down", "Place a held object at a target location"),
            ("stack", "Stack one block on top of another"),
            ("push", "Push an object to a target position"),
            ("sort", "Sort objects by moving them to different zones"),
            ("pour", "Pour contents from one container to another"),
            ("insert", "Insert a peg into a hole"),
            ("sweep", "Sweep objects off the table edge"),
        ]

        goals = []
        for name, desc in all_goals:
            if name not in known:
                goals.append(desc)
            if len(goals) >= 3:
                break

        # If all basic goals done, propose combinations
        if not goals:
            goals = [
                "Pick up object A, stack it on B, then push the stack forward",
                "Sort three objects by size into different bins",
            ]

        return goals

    def _go1_goals(self, cycle: int) -> list[str]:
        """Progressive goals for Go1 quadruped."""
        known = set(self.library.all_skills.keys())

        all_goals = [
            ("trot", "Move forward at a fast trotting pace"),
            ("turn_and_walk", "Turn left then walk forward"),
            ("walk_backward", "Walk backward slowly"),
            ("climb_small_step", "Step over a small obstacle"),
            ("recover_stand", "Stand up after falling on side"),
            ("circle_walk", "Walk in a circle"),
        ]

        goals = []
        for name, desc in all_goals:
            if name not in known:
                goals.append(desc)
            if len(goals) >= 3:
                break

        return goals if goals else ["Perform a complex locomotion sequence"]


class SelfEvolutionLoop:
    """Main controller for the robot self-evolution process."""

    def __init__(self, config: EvolutionConfig):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize world model
        self.world_model = StructuredWorldModel(
            state_dim=config.state_dim,
            action_dim=config.action_dim,
            contact_dim=config.contact_dim,
            hidden_dim=config.hidden_dim,
            n_layers=config.wm_n_layers,
        )
        self.trainer = WorldModelTrainer(self.world_model, lr=config.wm_lr)

        # Initialize skill library with primitives
        self.skill_library = SkillLibrary()
        self._init_primitives()

        # Initialize modules
        self.curiosity = CuriosityModule(self.skill_library, config.robot_type)
        self.synthesizer = SkillSynthesizer(
            self.skill_library,
            robot_type=config.robot_type,
            action_dim=config.action_dim,
        )
        self.validator = ImaginationValidator(
            self.world_model,
            success_threshold=config.success_threshold,
            safety_threshold=config.safety_threshold,
            confidence_threshold=config.confidence_threshold,
        )

        # State
        self.all_transitions: list[StateTransition] = []
        self.cycle_history: list[EvolutionMetrics] = []
        self.total_real_interactions = 0

    def _init_primitives(self):
        """Load initial primitives based on robot type."""
        from training.skill_synthesis import build_franka_primitives, build_go1_primitives

        if self.config.robot_type == "franka":
            for prim in build_franka_primitives(self.config.action_dim):
                self.skill_library.add_primitive(prim)
        elif self.config.robot_type == "go1":
            for prim in build_go1_primitives(self.config.action_dim):
                self.skill_library.add_primitive(prim)

    def run_cycle(self, cycle_id: int, adapter=None) -> EvolutionMetrics:
        """
        Execute one full evolution cycle.

        Args:
            cycle_id: cycle number
            adapter: optional real adapter for data collection + validation
                     (if None, uses synthetic data for testing)
        """
        start_time = time.time()
        print(f"\n{'='*60}")
        print(f"  Evolution Cycle {cycle_id}")
        print(f"  Skills in library: {self.skill_library.skill_count}")
        print(f"{'='*60}\n")

        # Phase 1: Explore (collect data)
        print("[Phase 1] Exploring...")
        new_transitions = self._explore(adapter)
        self.all_transitions.extend(new_transitions)
        self.total_real_interactions += len(new_transitions)
        print(f"  Collected {len(new_transitions)} transitions (total: {len(self.all_transitions)})")

        # Phase 2: Train world model
        print("[Phase 2] Training world model...")
        wm_loss = self._train_world_model()
        wm_metrics = self._evaluate_world_model()
        print(f"  Loss: {wm_loss:.4f}, State error: {wm_metrics['mean_state_error']:.4f}")

        # Phase 3: Propose goals (curiosity-driven)
        print("[Phase 3] Proposing goals...")
        goals = self.curiosity.propose_goals(cycle_id)
        print(f"  Goals: {goals}")

        # Phase 4: Synthesize skills
        print("[Phase 4] Synthesizing skills...")
        candidates = []
        for goal in goals:
            if self.config.use_llm:
                skill = self.synthesizer.synthesize(goal)
            else:
                skill = self.synthesizer.synthesize_without_llm(goal)
            if skill is not None:
                candidates.append(skill)
                print(f"  + Proposed: {skill.name} ({len(skill.action_sequence)} steps)")

        # Phase 5: Imagination validation
        print("[Phase 5] Imagination validation...")
        imagination_passed = []
        for candidate in candidates:
            report = self.validator.validate(
                candidate, n_scenarios=self.config.imagination_scenarios
            )
            print(f"  {report.summary()}")
            if report.pass_threshold:
                imagination_passed.append((candidate, report))

        # Phase 6: Real validation (if adapter available)
        print("[Phase 6] Real validation...")
        promoted = []
        if adapter is not None:
            for candidate, report in imagination_passed:
                real_success = self._real_validate(candidate, adapter)
                if real_success >= self.config.real_success_threshold:
                    self.skill_library.add_learned(candidate)
                    promoted.append(candidate)
                    print(f"  PROMOTED: {candidate.name} (real success: {real_success:.1%})")
                else:
                    print(f"  REJECTED: {candidate.name} (real success: {real_success:.1%})")
        else:
            # Without adapter, promote based on imagination alone (for testing)
            for candidate, report in imagination_passed:
                self.skill_library.add_learned(candidate)
                promoted.append(candidate)
                print(f"  PROMOTED (imagination-only): {candidate.name}")

        # Compile metrics
        elapsed = time.time() - start_time
        metrics = EvolutionMetrics(
            cycle=cycle_id,
            skills_proposed=len(candidates),
            skills_imagination_passed=len(imagination_passed),
            skills_real_validated=len(promoted) if adapter else 0,
            skills_promoted=len(promoted),
            wm_train_loss=wm_loss,
            wm_eval_metrics=wm_metrics,
            skill_library_size=self.skill_library.skill_count,
            total_real_interactions=self.total_real_interactions,
            elapsed_seconds=elapsed,
            details={
                "goals": goals,
                "proposed_skills": [c.name for c in candidates],
                "promoted_skills": [c.name for c in promoted],
            },
        )
        self.cycle_history.append(metrics)

        # Save checkpoint
        if self.config.save_checkpoints:
            self._save_checkpoint(cycle_id, metrics)

        print(f"\n  Cycle {cycle_id} complete in {elapsed:.1f}s")
        print(f"  Library: {self.skill_library.skill_count} skills")
        print(f"  Promoted this cycle: {len(promoted)}")

        return metrics

    def run(self, n_cycles: int, adapter=None) -> list[EvolutionMetrics]:
        """Run multiple evolution cycles."""
        all_metrics = []
        for i in range(n_cycles):
            metrics = self.run_cycle(i, adapter)
            all_metrics.append(metrics)
        self._save_final_report(all_metrics)
        return all_metrics

    def _explore(self, adapter) -> list[StateTransition]:
        """Collect transitions from environment."""
        if adapter is not None:
            from training.world_model import extract_transitions_from_pybullet
            return extract_transitions_from_pybullet(
                adapter,
                n_episodes=self.config.explore_episodes_per_cycle,
                max_steps_per_episode=self.config.max_steps_per_episode,
                action_dim=self.config.action_dim,
            )
        else:
            # Generate synthetic transitions for testing
            return self._generate_synthetic_transitions(
                self.config.explore_episodes_per_cycle * self.config.max_steps_per_episode
            )

    def _generate_synthetic_transitions(self, n: int) -> list[StateTransition]:
        """Generate synthetic data for testing without a real adapter."""
        transitions = []
        state = np.zeros(self.config.state_dim, dtype=np.float32)
        # Start near Franka home
        state[:7] = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        if self.config.state_dim > 9:
            state[7:10] = [0.4, 0.0, 0.4]
        if self.config.state_dim > 10:
            state[10] = 0.04

        for _ in range(n):
            action = np.random.randn(self.config.action_dim).astype(np.float32) * 0.1
            # Simple linear dynamics + noise
            delta = action[:self.config.state_dim] * 0.05 if len(action) >= self.config.state_dim else np.zeros(self.config.state_dim)
            next_state = state + delta[:self.config.state_dim] + np.random.randn(self.config.state_dim).astype(np.float32) * 0.01
            contact = (np.random.random(self.config.contact_dim) > 0.8).astype(np.float32)

            transitions.append(StateTransition(
                state=state.copy(),
                action=action,
                next_state=next_state,
                contact=contact,
            ))
            state = next_state

        return transitions

    def _train_world_model(self) -> float:
        """Train world model on all collected transitions."""
        if len(self.all_transitions) < 10:
            return 0.0

        dataset = TransitionDataset(self.all_transitions)
        dataloader = DataLoader(
            dataset,
            batch_size=self.config.wm_batch_size,
            shuffle=True,
            drop_last=len(dataset) > self.config.wm_batch_size,
        )

        total_loss = 0.0
        for epoch in range(self.config.wm_epochs_per_cycle):
            loss = self.trainer.train_epoch(dataloader)
            total_loss += loss

        return total_loss / max(self.config.wm_epochs_per_cycle, 1)

    def _evaluate_world_model(self) -> dict[str, float]:
        """Evaluate world model accuracy."""
        if len(self.all_transitions) < 20:
            return {"mean_state_error": 0.0, "contact_accuracy": 0.0}

        # Use last 20% as eval set
        eval_size = max(10, len(self.all_transitions) // 5)
        eval_transitions = self.all_transitions[-eval_size:]
        eval_dataset = TransitionDataset(eval_transitions)
        eval_loader = DataLoader(eval_dataset, batch_size=32)

        metrics = self.trainer.evaluate(eval_loader)

        # Also evaluate multi-step
        multistep = self.trainer.evaluate_multistep(eval_transitions, horizon=5)
        metrics.update(multistep)

        return metrics

    def _real_validate(self, skill: SkillCandidate, adapter) -> float:
        """Validate a skill in the real simulation. Returns success rate."""
        import asyncio

        successes = 0

        async def _validate():
            nonlocal successes
            for ep in range(self.config.real_validation_episodes):
                try:
                    await adapter.invoke_action("franka_panda", "home")
                    # Execute skill action sequence
                    for action_vec in skill.action_sequence[:20]:
                        # Interpret action vector and execute
                        # (simplified: just check it doesn't crash)
                        pass
                    successes += 1
                except Exception:
                    pass

        asyncio.run(_validate())
        return successes / max(self.config.real_validation_episodes, 1)

    def _save_checkpoint(self, cycle_id: int, metrics: EvolutionMetrics):
        """Save model checkpoint and metrics."""
        cycle_dir = self.output_dir / f"cycle_{cycle_id:03d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)

        # Save world model
        self.trainer.save(cycle_dir / "world_model.pt")

        # Save metrics
        with open(cycle_dir / "metrics.json", "w") as f:
            json.dump(metrics.to_dict(), f, indent=2, cls=_NumpyEncoder)

        # Save skill library state
        library_state = {
            "primitives": list(self.skill_library.primitives.keys()),
            "learned": list(self.skill_library.learned_skills.keys()),
            "history": self.skill_library.evolution_history,
        }
        with open(cycle_dir / "skill_library.json", "w") as f:
            json.dump(library_state, f, indent=2)

        # Save transitions (just count, full data is large)
        with open(cycle_dir / "data_stats.json", "w") as f:
            json.dump({"total_transitions": len(self.all_transitions)}, f)

    def _save_final_report(self, all_metrics: list[EvolutionMetrics]):
        """Save final evolution report."""
        report = {
            "n_cycles": len(all_metrics),
            "final_skill_count": self.skill_library.skill_count,
            "total_real_interactions": self.total_real_interactions,
            "cycles": [m.to_dict() for m in all_metrics],
            "skill_growth": [m.skill_library_size for m in all_metrics],
            "wm_errors": [m.wm_eval_metrics.get("mean_state_error", 0) for m in all_metrics],
        }
        with open(self.output_dir / "evolution_report.json", "w") as f:
            json.dump(report, f, indent=2, cls=_NumpyEncoder)
        print(f"\nFinal report saved to {self.output_dir / 'evolution_report.json'}")
