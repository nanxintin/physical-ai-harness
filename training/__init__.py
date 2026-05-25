"""Training pipeline for Physical AI Harness.

Generates training data by running LLM agents against simulation environments,
then exports trajectories for VERL post-training (GRPO).
"""

from training.trajectory import Trajectory
from training.reward import compute_score

__all__ = ["Trajectory", "compute_score"]
