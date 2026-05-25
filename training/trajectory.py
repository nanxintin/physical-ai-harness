"""Data class for recording agent-environment interaction trajectories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Trajectory:
    """A single episode of agent-environment interaction.

    Records the full conversation, tool calls, and outcome metadata needed
    for reward computation and VERL export.
    """

    task_id: str
    task_type: str  # "robot_control", "device_control", "navigation", "multi_device"
    messages: list[dict]  # Full conversation history
    tool_calls: list[dict]  # {name, arguments, result, success, timestamp}
    success: bool
    total_steps: int
    total_time_ms: float
    final_state: dict
    ground_truth: dict
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize trajectory to a plain dictionary."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "messages": self.messages,
            "tool_calls": self.tool_calls,
            "success": self.success,
            "total_steps": self.total_steps,
            "total_time_ms": self.total_time_ms,
            "final_state": self.final_state,
            "ground_truth": self.ground_truth,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Trajectory:
        """Reconstruct a Trajectory from a dictionary."""
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            messages=data["messages"],
            tool_calls=data["tool_calls"],
            success=data["success"],
            total_steps=data["total_steps"],
            total_time_ms=data["total_time_ms"],
            final_state=data["final_state"],
            ground_truth=data["ground_truth"],
            metadata=data.get("metadata", {}),
        )

    def save_json(self, path: str | Path) -> None:
        """Save trajectory to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_json(cls, path: str | Path) -> Trajectory:
        """Load trajectory from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)
