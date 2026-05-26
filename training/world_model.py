"""Structured World Model for robotic state transition prediction.

Predicts (state_t, action_t) → (state_{t+1}, contact, progress) in the
robot's structured state space (joint angles, EE position, object states)
rather than pixel-level prediction.

Designed for fast imagination rollouts to validate skill candidates.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import Dataset, DataLoader
except ImportError:
    raise ImportError(
        "PyTorch is required for world model training. "
        "Install with: pip install torch>=2.0.0"
    )


# --- Data Structures ---


@dataclass
class RobotState:
    """Structured robot state derived from CDD device state."""

    joint_positions: np.ndarray  # [n_joints]
    ee_position: np.ndarray  # [3] end-effector xyz
    gripper_width: float
    object_positions: dict[str, np.ndarray] = field(default_factory=dict)
    body_height: float = 0.0  # for quadrupeds
    body_orientation: np.ndarray = field(default_factory=lambda: np.zeros(3))
    contact_flags: np.ndarray = field(default_factory=lambda: np.zeros(4))

    def to_vector(self) -> np.ndarray:
        """Flatten to fixed-size vector for model input."""
        parts = [
            self.joint_positions,
            self.ee_position,
            np.array([self.gripper_width]),
            np.array([self.body_height]),
            self.body_orientation,
            self.contact_flags,
        ]
        for obj_pos in sorted(self.object_positions.values(), key=lambda x: x.tobytes()):
            parts.append(obj_pos)
        return np.concatenate(parts).astype(np.float32)

    @property
    def dim(self) -> int:
        return len(self.to_vector())


@dataclass
class RobotAction:
    """Unified action representation."""

    action_type: str  # "joint_target" | "ee_delta" | "locomotion" | "gripper"
    values: np.ndarray  # action-specific parameters
    duration: float = 0.1

    def to_vector(self, max_dim: int = 16) -> np.ndarray:
        """Encode action as fixed-size vector."""
        type_map = {"joint_target": 0, "ee_delta": 1, "locomotion": 2, "gripper": 3}
        type_id = type_map.get(self.action_type, 0)

        vec = np.zeros(max_dim, dtype=np.float32)
        vec[0] = type_id / 3.0  # normalized type
        vec[1] = self.duration
        n = min(len(self.values), max_dim - 2)
        vec[2 : 2 + n] = self.values[:n]
        return vec


@dataclass
class StateTransition:
    """A single (s, a, s') transition for world model training."""

    state: np.ndarray
    action: np.ndarray
    next_state: np.ndarray
    contact: np.ndarray  # contact forces/flags at next step
    reward: float = 0.0
    done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.tolist(),
            "action": self.action.tolist(),
            "next_state": self.next_state.tolist(),
            "contact": self.contact.tolist(),
            "reward": self.reward,
            "done": self.done,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StateTransition:
        return cls(
            state=np.array(d["state"], dtype=np.float32),
            action=np.array(d["action"], dtype=np.float32),
            next_state=np.array(d["next_state"], dtype=np.float32),
            contact=np.array(d["contact"], dtype=np.float32),
            reward=d.get("reward", 0.0),
            done=d.get("done", False),
        )


# --- Dataset ---


class TransitionDataset(Dataset):
    """PyTorch dataset of state transitions."""

    def __init__(self, transitions: list[StateTransition]):
        self.states = torch.tensor(
            np.array([t.state for t in transitions]), dtype=torch.float32
        )
        self.actions = torch.tensor(
            np.array([t.action for t in transitions]), dtype=torch.float32
        )
        self.next_states = torch.tensor(
            np.array([t.next_state for t in transitions]), dtype=torch.float32
        )
        self.contacts = torch.tensor(
            np.array([t.contact for t in transitions]), dtype=torch.float32
        )
        self.dones = torch.tensor(
            [t.done for t in transitions], dtype=torch.float32
        )

    def __len__(self) -> int:
        return len(self.states)

    def __getitem__(self, idx: int):
        return (
            self.states[idx],
            self.actions[idx],
            self.next_states[idx],
            self.contacts[idx],
            self.dones[idx],
        )


# --- Model Components ---


class StateEncoder(nn.Module):
    """Encode robot state vector."""

    def __init__(self, state_dim: int, hidden_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
        )

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.net(state)


class ActionEncoder(nn.Module):
    """Encode action vector."""

    def __init__(self, action_dim: int, hidden_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(action_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
        )

    def forward(self, action: torch.Tensor) -> torch.Tensor:
        return self.net(action)


class DynamicsTransformer(nn.Module):
    """Transformer block for state transition prediction."""

    def __init__(self, hidden_dim: int, n_heads: int = 4, n_layers: int = 4):
        super().__init__()
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=n_heads,
            dim_feedforward=hidden_dim * 4,
            dropout=0.1,
            activation="gelu",
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.input_proj = nn.Linear(hidden_dim * 2, hidden_dim)

    def forward(self, state_emb: torch.Tensor, action_emb: torch.Tensor) -> torch.Tensor:
        combined = torch.cat([state_emb, action_emb], dim=-1)
        x = self.input_proj(combined).unsqueeze(1)  # [B, 1, H]
        out = self.transformer(x)
        return out.squeeze(1)  # [B, H]


# --- Main World Model ---


class StructuredWorldModel(nn.Module):
    """
    Structured World Model: predicts state transitions in robot state space.

    Input: (state_t, action_t) as vectors
    Output: (predicted_state_{t+1}, contact_prediction, progress_value)
    """

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        contact_dim: int = 4,
        hidden_dim: int = 256,
        n_heads: int = 4,
        n_layers: int = 4,
    ):
        super().__init__()
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.contact_dim = contact_dim
        self.hidden_dim = hidden_dim

        self.state_encoder = StateEncoder(state_dim, hidden_dim)
        self.action_encoder = ActionEncoder(action_dim, hidden_dim)
        self.dynamics = DynamicsTransformer(hidden_dim, n_heads, n_layers)

        # Prediction heads
        self.state_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, state_dim),
        )
        self.contact_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Linear(hidden_dim // 2, contact_dim),
            nn.Sigmoid(),
        )
        self.progress_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Linear(hidden_dim // 2, 1),
            nn.Sigmoid(),
        )
        # Uncertainty estimation head
        self.uncertainty_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Linear(hidden_dim // 2, state_dim),
            nn.Softplus(),
        )

    def forward(
        self, state: torch.Tensor, action: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Predict next state, contact, progress, and uncertainty.

        Returns:
            next_state: predicted state [B, state_dim]
            contact: contact probabilities [B, contact_dim]
            progress: task progress [B, 1]
            uncertainty: prediction uncertainty per dimension [B, state_dim]
        """
        s_emb = self.state_encoder(state)
        a_emb = self.action_encoder(action)
        h = self.dynamics(s_emb, a_emb)

        # Residual prediction: predict delta, add to current state
        state_delta = self.state_head(h)
        next_state = state + state_delta

        contact = self.contact_head(h)
        progress = self.progress_head(h)
        uncertainty = self.uncertainty_head(h)

        return next_state, contact, progress, uncertainty

    def rollout(
        self,
        init_state: torch.Tensor,
        action_sequence: torch.Tensor,
        max_steps: int | None = None,
    ) -> dict[str, torch.Tensor]:
        """
        Multi-step imagination rollout.

        Args:
            init_state: initial state [state_dim] or [1, state_dim]
            action_sequence: actions [T, action_dim]
            max_steps: optional cap on rollout length

        Returns:
            Dictionary with states, contacts, progress, uncertainty trajectories.
        """
        if init_state.dim() == 1:
            init_state = init_state.unsqueeze(0)

        T = len(action_sequence)
        if max_steps is not None:
            T = min(T, max_steps)

        states = [init_state]
        contacts = []
        progress_values = []
        uncertainties = []

        current_state = init_state
        with torch.no_grad():
            for t in range(T):
                action = action_sequence[t].unsqueeze(0)
                next_state, contact, progress, uncertainty = self.forward(
                    current_state, action
                )
                states.append(next_state)
                contacts.append(contact)
                progress_values.append(progress)
                uncertainties.append(uncertainty)
                current_state = next_state

        return {
            "states": torch.cat(states, dim=0),  # [T+1, state_dim]
            "contacts": torch.cat(contacts, dim=0),  # [T, contact_dim]
            "progress": torch.cat(progress_values, dim=0),  # [T, 1]
            "uncertainty": torch.cat(uncertainties, dim=0),  # [T, state_dim]
        }

    def prediction_confidence(self, uncertainty: torch.Tensor) -> float:
        """Convert uncertainty to a 0-1 confidence score."""
        mean_unc = uncertainty.mean().item()
        return math.exp(-mean_unc)


# --- Training ---


class WorldModelTrainer:
    """Trainer for the Structured World Model."""

    def __init__(
        self,
        model: StructuredWorldModel,
        lr: float = 3e-4,
        weight_decay: float = 1e-5,
        state_loss_weight: float = 1.0,
        contact_loss_weight: float = 0.5,
        uncertainty_weight: float = 0.1,
    ):
        self.model = model
        self.optimizer = torch.optim.AdamW(
            model.parameters(), lr=lr, weight_decay=weight_decay
        )
        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=100
        )
        self.state_loss_weight = state_loss_weight
        self.contact_loss_weight = contact_loss_weight
        self.uncertainty_weight = uncertainty_weight
        self.train_losses: list[float] = []

    def train_epoch(self, dataloader: DataLoader) -> float:
        """Train for one epoch. Returns mean loss."""
        self.model.train()
        total_loss = 0.0
        n_batches = 0

        for states, actions, next_states, contacts, dones in dataloader:
            pred_next, pred_contact, pred_progress, uncertainty = self.model(
                states, actions
            )

            # State prediction loss (Gaussian NLL with learned variance)
            state_mse = F.mse_loss(pred_next, next_states, reduction="none")
            nll_loss = (
                state_mse / (2 * uncertainty.clamp(min=1e-6))
                + 0.5 * torch.log(uncertainty.clamp(min=1e-6))
            )
            state_loss = nll_loss.mean()

            # Contact prediction loss (BCE)
            contact_loss = F.binary_cross_entropy(pred_contact, contacts)

            # Combined loss
            loss = (
                self.state_loss_weight * state_loss
                + self.contact_loss_weight * contact_loss
            )

            self.optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            self.optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        self.scheduler.step()
        mean_loss = total_loss / max(n_batches, 1)
        self.train_losses.append(mean_loss)
        return mean_loss

    def evaluate(
        self, dataloader: DataLoader
    ) -> dict[str, float]:
        """Evaluate model on a dataset. Returns metrics dict."""
        self.model.eval()
        all_state_errors = []
        all_contact_acc = []

        with torch.no_grad():
            for states, actions, next_states, contacts, dones in dataloader:
                pred_next, pred_contact, _, uncertainty = self.model(states, actions)

                # Per-dimension absolute error
                state_error = (pred_next - next_states).abs().mean(dim=0)
                all_state_errors.append(state_error)

                # Contact accuracy
                contact_pred_binary = (pred_contact > 0.5).float()
                contact_acc = (contact_pred_binary == contacts).float().mean()
                all_contact_acc.append(contact_acc)

        mean_state_error = torch.stack(all_state_errors).mean(dim=0)
        mean_contact_acc = torch.tensor(all_contact_acc).mean().item()

        return {
            "mean_state_error": mean_state_error.mean().item(),
            "max_dim_error": mean_state_error.max().item(),
            "contact_accuracy": mean_contact_acc,
            "joint_error_rad": mean_state_error[:7].mean().item() if len(mean_state_error) > 7 else 0.0,
            "ee_error_m": mean_state_error[7:10].mean().item() if len(mean_state_error) > 10 else 0.0,
        }

    def evaluate_multistep(
        self, transitions: list[StateTransition], horizon: int = 5
    ) -> dict[str, float]:
        """Evaluate multi-step rollout accuracy."""
        self.model.eval()
        errors_by_step = {h: [] for h in range(1, horizon + 1)}

        # Group transitions into sequences
        sequences = self._group_sequences(transitions, horizon)

        with torch.no_grad():
            for seq in sequences:
                init_state = torch.tensor(seq[0].state, dtype=torch.float32).unsqueeze(0)
                actions = torch.tensor(
                    np.array([t.action for t in seq]), dtype=torch.float32
                )
                result = self.model.rollout(init_state, actions, max_steps=horizon)

                for h in range(min(horizon, len(seq))):
                    pred = result["states"][h + 1].numpy().flatten()
                    actual = seq[h].next_state
                    error = np.abs(pred - actual).mean()
                    errors_by_step[h + 1].append(error)

        return {
            f"step_{h}_error": np.mean(errors_by_step[h]) if errors_by_step[h] else 0.0
            for h in range(1, horizon + 1)
        }

    def _group_sequences(
        self, transitions: list[StateTransition], length: int
    ) -> list[list[StateTransition]]:
        """Group consecutive transitions into sequences of given length."""
        sequences = []
        for i in range(len(transitions) - length + 1):
            seq = transitions[i : i + length]
            # Check continuity: next_state of t should ≈ state of t+1
            valid = True
            for j in range(len(seq) - 1):
                if np.abs(seq[j].next_state - seq[j + 1].state).max() > 0.1:
                    valid = False
                    break
            if valid:
                sequences.append(seq)
        return sequences

    def save(self, path: str | Path):
        """Save model checkpoint."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model_state_dict": self.model.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "train_losses": self.train_losses,
                "config": {
                    "state_dim": self.model.state_dim,
                    "action_dim": self.model.action_dim,
                    "contact_dim": self.model.contact_dim,
                    "hidden_dim": self.model.hidden_dim,
                    "n_layers": len(self.model.dynamics.transformer.layers),
                },
            },
            path,
        )

    @classmethod
    def load(cls, path: str | Path, device: str = "cpu") -> WorldModelTrainer:
        """Load model from checkpoint."""
        checkpoint = torch.load(path, map_location=device, weights_only=False)
        config = checkpoint["config"]
        model = StructuredWorldModel(
            state_dim=config["state_dim"],
            action_dim=config["action_dim"],
            contact_dim=config["contact_dim"],
            hidden_dim=config["hidden_dim"],
            n_layers=config.get("n_layers", 4),
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        trainer = cls(model)
        trainer.train_losses = checkpoint.get("train_losses", [])
        return trainer


# --- Data Collection Utilities ---


def extract_transitions_from_pybullet(
    adapter,
    n_episodes: int = 100,
    max_steps_per_episode: int = 20,
    action_dim: int = 16,
) -> list[StateTransition]:
    """
    Collect state transitions by executing random actions in PyBullet.

    Args:
        adapter: initialized PyBulletArmAdapter instance
        n_episodes: number of episodes to collect
        max_steps_per_episode: max actions per episode
        action_dim: dimension of action vector

    Returns:
        List of StateTransition objects.
    """
    import asyncio

    transitions = []

    async def _collect():
        for ep in range(n_episodes):
            # Reset to home
            await adapter.invoke_action("franka_panda", "home")
            state_dict = await adapter.get_device_state("franka_panda")
            state_vec = _pybullet_state_to_vector(state_dict.properties)

            for step in range(max_steps_per_episode):
                # Random action: small joint perturbation or gripper change
                action, action_vec = _sample_random_action(state_dict.properties, action_dim)

                try:
                    new_state_dict = await adapter.set_property(
                        "franka_panda", action["property"], action["value"]
                    )
                except (ValueError, RuntimeError):
                    continue

                next_state_vec = _pybullet_state_to_vector(new_state_dict.properties)
                contact = np.zeros(4, dtype=np.float32)  # simplified

                transitions.append(StateTransition(
                    state=state_vec,
                    action=action_vec,
                    next_state=next_state_vec,
                    contact=contact,
                ))

                state_vec = next_state_vec
                state_dict = new_state_dict

    asyncio.run(_collect())
    return transitions


def _pybullet_state_to_vector(properties: dict) -> np.ndarray:
    """Convert PyBullet device state properties to a flat vector."""
    from harness.adapters.pybullet_arm.config import JOINT_NAMES

    parts = []
    # 7 joint positions
    for name in JOINT_NAMES:
        parts.append(properties.get(name, 0.0))
    # EE position
    ee = properties.get("end_effector_position", [0.0, 0.0, 0.0])
    parts.extend(ee)
    # Gripper
    parts.append(properties.get("gripper_width", 0.04))
    return np.array(parts, dtype=np.float32)


def _sample_random_action(properties: dict, action_dim: int) -> tuple[dict, np.ndarray]:
    """Sample a random action for the Franka arm."""
    from harness.adapters.pybullet_arm.config import JOINT_NAMES, JOINT_RANGES

    # Choose a random joint or gripper
    if np.random.random() < 0.8:
        joint_name = np.random.choice(JOINT_NAMES)
        low, high = JOINT_RANGES[joint_name]
        current = properties.get(joint_name, 0.0)
        delta = np.random.uniform(-0.2, 0.2)
        target = np.clip(current + delta, low, high)
        action_dict = {"property": joint_name, "value": target}
        action_vec = np.zeros(action_dim, dtype=np.float32)
        action_vec[0] = 0.0  # joint_target type
        action_vec[1] = 0.1  # duration
        idx = JOINT_NAMES.index(joint_name)
        action_vec[2 + idx] = delta
    else:
        current_gripper = properties.get("gripper_width", 0.04)
        target = 0.08 if current_gripper < 0.04 else 0.0
        action_dict = {"property": "gripper_width", "value": target}
        action_vec = np.zeros(action_dim, dtype=np.float32)
        action_vec[0] = 1.0  # gripper type
        action_vec[1] = 0.1
        action_vec[2] = target - current_gripper

    return action_dict, action_vec


def save_transitions(transitions: list[StateTransition], path: str | Path):
    """Save transitions to JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [t.to_dict() for t in transitions]
    with open(path, "w") as f:
        json.dump(data, f)


def load_transitions(path: str | Path) -> list[StateTransition]:
    """Load transitions from JSON file."""
    with open(path) as f:
        data = json.load(f)
    return [StateTransition.from_dict(d) for d in data]
