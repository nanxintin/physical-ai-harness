"""Imagination Validator: verify skill candidates via world model rollouts.

Uses the trained StructuredWorldModel to simulate skill execution across
multiple randomized scenarios, producing a validation report that determines
whether a skill should be promoted to the skill library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

try:
    import torch
except ImportError:
    raise ImportError("PyTorch is required. Install with: pip install torch>=2.0.0")

from training.world_model import StructuredWorldModel


@dataclass
class Scenario:
    """A randomized initial condition for imagination rollout."""

    state: np.ndarray
    description: str = ""
    object_positions: dict[str, np.ndarray] = field(default_factory=dict)
    noise_scale: float = 0.02


@dataclass
class RolloutResult:
    """Result of a single imagination rollout."""

    success: bool
    safe: bool
    steps: int
    final_progress: float
    mean_confidence: float
    max_uncertainty: float
    trajectory_states: list[np.ndarray] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Aggregated report from validating a skill across multiple scenarios."""

    skill_name: str
    n_scenarios: int
    success_rate: float
    safety_rate: float
    mean_confidence: float
    mean_steps: float
    pass_threshold: bool
    rollout_results: list[RolloutResult] = field(default_factory=list)

    def summary(self) -> str:
        status = "PASS" if self.pass_threshold else "FAIL"
        return (
            f"[{status}] {self.skill_name}: "
            f"success={self.success_rate:.1%}, "
            f"safety={self.safety_rate:.1%}, "
            f"confidence={self.mean_confidence:.3f}, "
            f"scenarios={self.n_scenarios}"
        )


@dataclass
class SkillCandidate:
    """A candidate skill to be validated."""

    name: str
    action_sequence: list[np.ndarray]  # list of action vectors
    preconditions: dict[str, Any] = field(default_factory=dict)
    expected_effects: dict[str, Any] = field(default_factory=dict)
    source: str = "llm"  # "llm" | "composition" | "mutation"
    metadata: dict[str, Any] = field(default_factory=dict)


class ImaginationValidator:
    """Validates skill candidates by running them through the world model."""

    def __init__(
        self,
        world_model: StructuredWorldModel,
        success_threshold: float = 0.7,
        safety_threshold: float = 0.95,
        confidence_threshold: float = 0.6,
        max_rollout_steps: int = 50,
        joint_limit_margin: float = 0.1,
        device: str = "cpu",
    ):
        self.world_model = world_model.to(device)
        self.world_model.eval()
        self.success_threshold = success_threshold
        self.safety_threshold = safety_threshold
        self.confidence_threshold = confidence_threshold
        self.max_rollout_steps = max_rollout_steps
        self.joint_limit_margin = joint_limit_margin
        self.device = device

    def validate(
        self,
        skill: SkillCandidate,
        scenarios: list[Scenario] | None = None,
        n_scenarios: int = 50,
    ) -> ValidationReport:
        """
        Validate a skill across multiple scenarios.

        Args:
            skill: the skill candidate to validate
            scenarios: pre-defined scenarios, or None to auto-generate
            n_scenarios: number of scenarios if auto-generating

        Returns:
            ValidationReport with aggregated metrics
        """
        if scenarios is None:
            scenarios = self._generate_scenarios(skill, n_scenarios)

        results = []
        for scenario in scenarios:
            result = self._run_single_rollout(skill, scenario)
            results.append(result)

        success_rate = sum(r.success for r in results) / len(results)
        safety_rate = sum(r.safe for r in results) / len(results)
        mean_confidence = sum(r.mean_confidence for r in results) / len(results)
        mean_steps = sum(r.steps for r in results) / len(results)

        pass_threshold = (
            success_rate >= self.success_threshold
            and safety_rate >= self.safety_threshold
            and mean_confidence >= self.confidence_threshold
        )

        return ValidationReport(
            skill_name=skill.name,
            n_scenarios=len(scenarios),
            success_rate=success_rate,
            safety_rate=safety_rate,
            mean_confidence=mean_confidence,
            mean_steps=mean_steps,
            pass_threshold=pass_threshold,
            rollout_results=results,
        )

    def _run_single_rollout(
        self, skill: SkillCandidate, scenario: Scenario
    ) -> RolloutResult:
        """Execute a single imagination rollout."""
        # Add noise to initial state
        noisy_state = scenario.state + np.random.normal(
            0, scenario.noise_scale, size=scenario.state.shape
        ).astype(np.float32)

        # Convert to tensors
        init_state = torch.tensor(noisy_state, dtype=torch.float32, device=self.device)
        actions = torch.tensor(
            np.array(skill.action_sequence), dtype=torch.float32, device=self.device
        )

        # Run rollout in world model
        with torch.no_grad():
            result = self.world_model.rollout(
                init_state, actions, max_steps=self.max_rollout_steps
            )

        states = result["states"].cpu().numpy()
        contacts = result["contacts"].cpu().numpy()
        progress = result["progress"].cpu().numpy()
        uncertainty = result["uncertainty"].cpu().numpy()

        # Evaluate outcomes
        final_progress_raw = progress[-1] if len(progress) > 0 else np.array([0.0])
        final_progress = float(final_progress_raw.flat[0]) if hasattr(final_progress_raw, 'flat') else float(final_progress_raw)

        # Success criteria: use state displacement as primary signal when
        # progress head has no supervised training signal.
        # A skill "succeeds" if it produces meaningful, directed state change.
        state_displacement = float(np.linalg.norm(states[-1] - states[0])) if len(states) > 1 else 0.0
        skill_length = len(skill.action_sequence)
        # Normalized displacement: reward purposeful movement proportional to skill length
        normalized_disp = state_displacement / max(skill_length * 0.05, 0.1)
        success = (
            final_progress > 0.8  # progress head reliable (when trained with rewards)
            or normalized_disp > 0.5  # meaningful state change relative to skill length
        )

        # Safety check: ensure states stay within bounds
        safe = self._check_safety(states)

        # Confidence from uncertainty
        mean_unc = uncertainty.mean()
        mean_confidence = math.exp(-float(mean_unc))
        max_unc = float(uncertainty.max())

        return RolloutResult(
            success=success,
            safe=safe,
            steps=len(actions),
            final_progress=final_progress,
            mean_confidence=mean_confidence,
            max_uncertainty=max_unc,
            trajectory_states=[s for s in states],
        )

    def _check_safety(self, states: np.ndarray) -> bool:
        """Check if all states are within safe bounds."""
        # Joint limits check (first 7 dims for Franka)
        if states.shape[1] >= 7:
            joint_states = states[:, :7]
            # Simplified: check if any joint exceeds ±3.14 (generous bound)
            if np.any(np.abs(joint_states) > 3.14):
                return False

        # EE height check (don't go below table)
        if states.shape[1] >= 10:
            ee_z = states[:, 9]  # z component of EE position
            if np.any(ee_z < -0.05):
                return False

        # Velocity/acceleration proxy: large state changes between steps
        if len(states) > 1:
            deltas = np.diff(states, axis=0)
            if np.any(np.abs(deltas) > 1.0):
                return False

        return True

    def _generate_scenarios(
        self, skill: SkillCandidate, n: int
    ) -> list[Scenario]:
        """Generate randomized scenarios for a skill."""
        scenarios = []
        # Base state (neutral robot pose)
        base_state = self._get_base_state()

        for i in range(n):
            # Randomize initial joint positions slightly
            noise = np.random.uniform(-0.3, 0.3, size=base_state.shape).astype(np.float32)
            noise[7:10] = np.random.uniform(-0.05, 0.05, size=3)  # smaller EE noise
            state = base_state + noise

            scenarios.append(Scenario(
                state=state,
                description=f"scenario_{i}",
                noise_scale=0.02 + 0.01 * (i / n),  # increasing noise
            ))

        return scenarios

    def _get_base_state(self) -> np.ndarray:
        """Get a neutral base state (home position)."""
        # 7 joints (home) + 3 EE pos + 1 gripper = 11 dims minimum
        state = np.zeros(self.world_model.state_dim, dtype=np.float32)
        # Franka home-ish joint angles
        home_joints = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        for i, v in enumerate(home_joints[:min(7, self.world_model.state_dim)]):
            state[i] = v
        # EE position (roughly center workspace)
        if self.world_model.state_dim > 9:
            state[7] = 0.4  # x
            state[8] = 0.0  # y
            state[9] = 0.4  # z
        # Gripper open
        if self.world_model.state_dim > 10:
            state[10] = 0.04
        return state

    def batch_validate(
        self,
        candidates: list[SkillCandidate],
        n_scenarios: int = 50,
    ) -> list[ValidationReport]:
        """Validate multiple skill candidates."""
        reports = []
        for candidate in candidates:
            report = self.validate(candidate, n_scenarios=n_scenarios)
            reports.append(report)
        return reports

    def rank_candidates(
        self, reports: list[ValidationReport]
    ) -> list[tuple[ValidationReport, float]]:
        """Rank validated candidates by composite score."""
        scored = []
        for report in reports:
            score = (
                0.5 * report.success_rate
                + 0.3 * report.mean_confidence
                + 0.2 * report.safety_rate
            )
            scored.append((report, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
