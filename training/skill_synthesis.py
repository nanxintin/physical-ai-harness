"""LLM-driven Skill Synthesizer for robot self-evolution.

Uses Claude to propose new skills by composing, parameterizing, or mutating
existing primitives, constrained by robot capabilities (CDD) and physical limits.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from training.imagination import SkillCandidate


@dataclass
class SkillPrimitive:
    """A basic robot primitive that can be composed into skills."""

    name: str
    description: str
    param_schema: dict[str, Any]  # parameter name → {type, range, default}
    action_template: list[dict]  # template action sequence
    preconditions: dict[str, Any] = field(default_factory=dict)
    effects: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillLibrary:
    """Registry of available skills (primitives + learned)."""

    primitives: dict[str, SkillPrimitive] = field(default_factory=dict)
    learned_skills: dict[str, SkillCandidate] = field(default_factory=dict)
    evolution_history: list[dict] = field(default_factory=list)

    def add_primitive(self, skill: SkillPrimitive):
        self.primitives[skill.name] = skill

    def add_learned(self, skill: SkillCandidate):
        self.learned_skills[skill.name] = skill
        self.evolution_history.append({
            "name": skill.name,
            "source": skill.source,
            "cycle": len(self.evolution_history),
        })

    @property
    def all_skills(self) -> dict[str, Any]:
        return {**self.primitives, **self.learned_skills}

    def describe_for_llm(self) -> str:
        """Generate a text description of available skills for LLM prompting."""
        lines = ["## Available Skills\n"]
        for name, prim in self.primitives.items():
            params_str = ", ".join(
                f"{k}: {v.get('type', 'float')}" for k, v in prim.param_schema.items()
            )
            lines.append(f"- **{name}**({params_str}): {prim.description}")
            if prim.preconditions:
                lines.append(f"  - Preconditions: {prim.preconditions}")
            if prim.effects:
                lines.append(f"  - Effects: {prim.effects}")

        if self.learned_skills:
            lines.append("\n## Learned Skills (previously synthesized)\n")
            for name, skill in self.learned_skills.items():
                lines.append(f"- **{name}**: {skill.metadata.get('description', '')}")
                lines.append(f"  - Source: {skill.source}")
                lines.append(f"  - Steps: {len(skill.action_sequence)}")

        return "\n".join(lines)

    @property
    def skill_count(self) -> int:
        return len(self.primitives) + len(self.learned_skills)


# --- Default Primitives for Franka Panda ---


def build_franka_primitives(action_dim: int = 16) -> list[SkillPrimitive]:
    """Create default primitives for Franka Panda arm."""
    return [
        SkillPrimitive(
            name="reach",
            description="Move end effector to target position (x, y, z)",
            param_schema={
                "x": {"type": "float", "range": [0.2, 0.8], "default": 0.4},
                "y": {"type": "float", "range": [-0.4, 0.4], "default": 0.0},
                "z": {"type": "float", "range": [0.05, 0.6], "default": 0.3},
            },
            action_template=[{"type": "ee_delta", "steps": 5}],
            preconditions={},
            effects={"ee_at_target": True},
        ),
        SkillPrimitive(
            name="grasp",
            description="Close gripper to grasp an object",
            param_schema={
                "force": {"type": "float", "range": [0.0, 1.0], "default": 0.8},
            },
            action_template=[{"type": "gripper", "target_width": 0.0}],
            preconditions={"gripper_open": True, "object_in_reach": True},
            effects={"holding_object": True},
        ),
        SkillPrimitive(
            name="release",
            description="Open gripper to release held object",
            param_schema={},
            action_template=[{"type": "gripper", "target_width": 0.08}],
            preconditions={"holding_object": True},
            effects={"holding_object": False},
        ),
    ]


def build_go1_primitives(action_dim: int = 16) -> list[SkillPrimitive]:
    """Create default primitives for Unitree Go1 quadruped."""
    return [
        SkillPrimitive(
            name="stand",
            description="Stand up in stable neutral pose",
            param_schema={},
            action_template=[{"type": "locomotion", "gait": "stand"}],
            preconditions={},
            effects={"standing": True, "stable": True},
        ),
        SkillPrimitive(
            name="walk_step",
            description="Take one step forward at given speed",
            param_schema={
                "speed": {"type": "float", "range": [0.1, 0.5], "default": 0.3},
            },
            action_template=[{"type": "locomotion", "gait": "walk", "steps": 10}],
            preconditions={"standing": True},
            effects={"moved_forward": True},
        ),
        SkillPrimitive(
            name="turn_step",
            description="Turn in place by a small angle",
            param_schema={
                "direction": {"type": "float", "range": [-1.0, 1.0], "default": 1.0},
            },
            action_template=[{"type": "locomotion", "gait": "turn", "steps": 8}],
            preconditions={"standing": True},
            effects={"turned": True},
        ),
    ]


# --- Skill Synthesizer ---


SYNTHESIS_PROMPT_TEMPLATE = """You are a robotics skill synthesizer. Your job is to compose new robot skills from existing primitives.

## Robot Capabilities
{robot_description}

## Physical Constraints
{constraints}

{skill_library}

## Task Goal
{goal}

## Instructions
Synthesize a NEW skill that achieves the goal by composing the available primitives.
Output a JSON object with this exact structure:

```json
{{
  "name": "skill_name_snake_case",
  "description": "What this skill does",
  "strategy": "composition|parameterization|mutation",
  "steps": [
    {{"primitive": "primitive_name", "params": {{"param1": value}}}},
    ...
  ],
  "preconditions": {{"condition": "value"}},
  "expected_effects": {{"effect": "value"}}
}}
```

Rules:
- Only use primitives listed above
- Respect physical constraints (joint limits, workspace bounds)
- Keep step count minimal (prefer 2-5 steps)
- Each step must use an existing primitive with valid parameters
- Name should be descriptive and unique
"""

FRANKA_DESCRIPTION = """
- Robot: Franka Panda 7-DOF arm with parallel-jaw gripper
- Gripper width: 0-0.08m
- Workspace: x[0.2,0.8], y[-0.4,0.4], z[0.05,0.6] meters
- Joint limits: 7 revolute joints, ranges ≈ ±2.8 rad
- Payload: max 3kg at end effector
"""

FRANKA_CONSTRAINTS = """
- Must approach objects from above for top-grasp
- Cannot grasp objects wider than 0.08m
- Stacking requires placement accuracy < 1cm
- Objects fall under gravity when released
- Cannot move through other objects (collision)
- Gripper must be open before grasping
- Must be holding object before releasing
"""

GO1_DESCRIPTION = """
- Robot: Unitree Go1 quadruped (12 joints: 4 legs × 3 joints each)
- Gait types: stand, walk, trot, turn
- Max speed: ~1.5 m/s (trot)
- Body height: 0.25-0.4m
- Cannot manipulate objects (no gripper)
- 4 foot contact sensors
"""

GO1_CONSTRAINTS = """
- Must be standing before walking/trotting
- High speeds (>0.8 m/s) risk instability
- Cannot climb slopes > 30 degrees
- Must maintain 2+ feet on ground for stability
- Rapid direction changes may cause fall
"""


class SkillSynthesizer:
    """LLM-driven skill synthesis with physical grounding."""

    def __init__(
        self,
        skill_library: SkillLibrary,
        robot_type: str = "franka",
        action_dim: int = 16,
        llm_client: Any = None,
    ):
        self.library = skill_library
        self.robot_type = robot_type
        self.action_dim = action_dim
        self.llm_client = llm_client

        if robot_type == "franka":
            self.robot_description = FRANKA_DESCRIPTION
            self.constraints = FRANKA_CONSTRAINTS
        elif robot_type == "go1":
            self.robot_description = GO1_DESCRIPTION
            self.constraints = GO1_CONSTRAINTS
        else:
            self.robot_description = ""
            self.constraints = ""

    def synthesize(self, goal: str) -> SkillCandidate | None:
        """
        Use LLM to synthesize a new skill for the given goal.

        Args:
            goal: natural language description of what the skill should achieve

        Returns:
            SkillCandidate if synthesis succeeds, None otherwise
        """
        prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            robot_description=self.robot_description,
            constraints=self.constraints,
            skill_library=self.library.describe_for_llm(),
            goal=goal,
        )

        try:
            response_text = self._call_llm(prompt)
        except Exception as e:
            print(f"    [LLM Error] {e}, falling back to rule-based")
            return self.synthesize_without_llm(goal)

        result = self._parse_response(response_text, goal)
        if result is None:
            # Fall back to rule-based if LLM response couldn't be parsed
            return self.synthesize_without_llm(goal)
        return result

    def synthesize_without_llm(self, goal: str) -> SkillCandidate | None:
        """
        Rule-based skill synthesis for testing (no LLM needed).
        Composes skills based on simple pattern matching.
        """
        goal_lower = goal.lower()

        if "pick" in goal_lower and "up" in goal_lower:
            return self._compose_pick_up()
        elif "stack" in goal_lower:
            return self._compose_stack()
        elif "push" in goal_lower:
            return self._compose_push()
        elif "trot" in goal_lower or "fast" in goal_lower:
            return self._compose_trot()
        elif "turn" in goal_lower and "walk" in goal_lower:
            return self._compose_turn_walk()

        return None

    def _compose_pick_up(self) -> SkillCandidate:
        """Compose a pick_up skill from reach + grasp."""
        actions = []
        # Step 1: reach above object
        actions.extend(self._primitive_to_actions("reach", {"x": 0.4, "y": 0.0, "z": 0.25}))
        # Step 2: lower to object
        actions.extend(self._primitive_to_actions("reach", {"x": 0.4, "y": 0.0, "z": 0.08}))
        # Step 3: grasp
        actions.extend(self._primitive_to_actions("grasp", {"force": 0.8}))
        # Step 4: lift
        actions.extend(self._primitive_to_actions("reach", {"x": 0.4, "y": 0.0, "z": 0.3}))

        return SkillCandidate(
            name="pick_up",
            action_sequence=actions,
            preconditions={"object_on_table": True, "gripper_open": True},
            expected_effects={"holding_object": True, "object_lifted": True},
            source="composition",
            metadata={"description": "Pick up an object from the table", "components": ["reach", "grasp"]},
        )

    def _compose_stack(self) -> SkillCandidate:
        """Compose a stack skill from pick + move + place."""
        actions = []
        # Pick up first object
        actions.extend(self._primitive_to_actions("reach", {"x": 0.3, "y": 0.0, "z": 0.08}))
        actions.extend(self._primitive_to_actions("grasp", {"force": 0.8}))
        actions.extend(self._primitive_to_actions("reach", {"x": 0.3, "y": 0.0, "z": 0.3}))
        # Move to second object
        actions.extend(self._primitive_to_actions("reach", {"x": 0.5, "y": 0.0, "z": 0.2}))
        # Lower and release
        actions.extend(self._primitive_to_actions("reach", {"x": 0.5, "y": 0.0, "z": 0.12}))
        actions.extend(self._primitive_to_actions("release", {}))

        return SkillCandidate(
            name="stack",
            action_sequence=actions,
            preconditions={"two_objects_on_table": True, "gripper_open": True},
            expected_effects={"objects_stacked": True},
            source="composition",
            metadata={"description": "Stack one object on top of another", "components": ["reach", "grasp", "release"]},
        )

    def _compose_push(self) -> SkillCandidate:
        """Compose a push skill."""
        actions = []
        actions.extend(self._primitive_to_actions("reach", {"x": 0.3, "y": 0.0, "z": 0.08}))
        # Push forward
        actions.extend(self._primitive_to_actions("reach", {"x": 0.5, "y": 0.0, "z": 0.08}))

        return SkillCandidate(
            name="push",
            action_sequence=actions,
            preconditions={"object_in_front": True},
            expected_effects={"object_moved_forward": True},
            source="composition",
            metadata={"description": "Push an object forward on the table"},
        )

    def _compose_trot(self) -> SkillCandidate:
        """Compose a trot (fast walk) for quadruped."""
        actions = []
        # Stand first
        actions.extend(self._locomotion_actions("stand", 5))
        # Trot
        actions.extend(self._locomotion_actions("trot", 20, speed=0.6))

        return SkillCandidate(
            name="trot",
            action_sequence=actions,
            preconditions={"standing": True},
            expected_effects={"moved_forward_fast": True},
            source="parameterization",
            metadata={"description": "Fast trotting gait", "base_skill": "walk_step"},
        )

    def _compose_turn_walk(self) -> SkillCandidate:
        """Compose turn + walk for quadruped."""
        actions = []
        actions.extend(self._locomotion_actions("turn", 8, direction=1.0))
        actions.extend(self._locomotion_actions("walk", 15, speed=0.3))

        return SkillCandidate(
            name="turn_and_walk",
            action_sequence=actions,
            preconditions={"standing": True},
            expected_effects={"turned_and_moved": True},
            source="composition",
            metadata={"description": "Turn left then walk forward", "components": ["turn_step", "walk_step"]},
        )

    def _primitive_to_actions(self, primitive_name: str, params: dict) -> list[np.ndarray]:
        """Convert a primitive call to action vectors."""
        actions = []
        if primitive_name == "reach":
            # Generate 5 interpolation steps toward target
            target = np.array([params.get("x", 0.4), params.get("y", 0.0), params.get("z", 0.3)])
            for i in range(5):
                action = np.zeros(self.action_dim, dtype=np.float32)
                action[0] = 1.0 / 3.0  # ee_delta type
                action[1] = 0.1  # duration
                action[2:5] = target / 5  # distribute delta
                actions.append(action)
        elif primitive_name == "grasp":
            action = np.zeros(self.action_dim, dtype=np.float32)
            action[0] = 3.0 / 3.0  # gripper type
            action[1] = 0.1
            action[2] = -0.04  # close
            actions.append(action)
        elif primitive_name == "release":
            action = np.zeros(self.action_dim, dtype=np.float32)
            action[0] = 3.0 / 3.0  # gripper type
            action[1] = 0.1
            action[2] = 0.04  # open
            actions.append(action)
        return actions

    def _locomotion_actions(
        self, gait: str, n_steps: int, speed: float = 0.3, direction: float = 0.0
    ) -> list[np.ndarray]:
        """Generate locomotion action vectors for quadruped."""
        gait_map = {"stand": 0.0, "walk": 0.25, "trot": 0.5, "turn": 0.75}
        actions = []
        for _ in range(n_steps):
            action = np.zeros(self.action_dim, dtype=np.float32)
            action[0] = 2.0 / 3.0  # locomotion type
            action[1] = 0.05  # duration per step
            action[2] = gait_map.get(gait, 0.0)
            action[3] = speed
            action[4] = direction
            actions.append(action)
        return actions

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM API. Auto-detects Anthropic client from environment."""
        import os

        if self.llm_client is None:
            try:
                import anthropic
                self.llm_client = anthropic.Anthropic()
            except Exception as e:
                raise RuntimeError(f"Failed to create Anthropic client: {e}")

        if hasattr(self.llm_client, "messages"):
            # Resolve model from env or use default
            model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")
            response = self.llm_client.messages.create(
                model=model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        elif hasattr(self.llm_client, "chat"):
            response = self.llm_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
            return response.choices[0].message.content
        else:
            raise ValueError("Unsupported LLM client")

    def _parse_response(self, response_text: str, goal: str) -> SkillCandidate | None:
        """Parse LLM response into a SkillCandidate."""
        # Extract JSON from response
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if not json_match:
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group(1) if json_match.lastindex else json_match.group(0))
        except json.JSONDecodeError:
            return None

        # Convert steps to action vectors
        actions = []
        for step in data.get("steps", []):
            primitive_name = step.get("primitive", "")
            params = step.get("params", {})
            step_actions = self._primitive_to_actions(primitive_name, params)
            actions.extend(step_actions)

        if not actions:
            return None

        return SkillCandidate(
            name=data.get("name", "unnamed_skill"),
            action_sequence=actions,
            preconditions=data.get("preconditions", {}),
            expected_effects=data.get("expected_effects", {}),
            source=data.get("strategy", "composition"),
            metadata={
                "description": data.get("description", ""),
                "goal": goal,
                "raw_steps": data.get("steps", []),
            },
        )
