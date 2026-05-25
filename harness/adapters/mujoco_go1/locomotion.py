"""Simple open-loop gait generators for Unitree Go1."""

from __future__ import annotations

import math

from harness.adapters.mujoco_go1.robot_config import STAND_POSE, SIT_POSE


class GaitController:
    """Sinusoidal open-loop gait generator."""

    def __init__(self):
        self._phase = 0.0

    def stand(self) -> list[float]:
        return list(STAND_POSE)

    def sit(self) -> list[float]:
        return list(SIT_POSE)

    def stop(self) -> list[float]:
        self._phase = 0.0
        return list(STAND_POSE)

    def walk(self, phase: float, speed: float = 0.3) -> list[float]:
        """Generate walking targets for a given phase.

        Trot gait: FR+RL in phase, FL+RR 180 degrees out.
        """
        amp_hip = 0.1 * speed
        amp_thigh = 0.3 * speed
        amp_calf = 0.2 * speed

        targets = []
        for leg_idx in range(4):
            leg_phase = phase if leg_idx in (0, 3) else phase + math.pi
            hip = amp_hip * math.sin(leg_phase)
            thigh = 0.8 + amp_thigh * math.sin(leg_phase)
            calf = -1.6 + amp_calf * math.sin(leg_phase + 0.5)
            targets.extend([hip, thigh, calf])
        return targets

    def trot(self, phase: float, speed: float = 0.6) -> list[float]:
        """Faster trot gait with larger amplitudes."""
        return self.walk(phase, speed=speed)

    def turn(self, phase: float, direction: float = 1.0) -> list[float]:
        """Turn in place. direction: 1.0 = left, -1.0 = right."""
        amp = 0.15 * abs(direction)
        targets = []
        for leg_idx in range(4):
            leg_phase = phase if leg_idx in (0, 3) else phase + math.pi
            if leg_idx in (0, 1):  # front legs
                hip = amp * direction * math.sin(leg_phase)
            else:  # rear legs
                hip = -amp * direction * math.sin(leg_phase)
            thigh = 0.8 + 0.15 * math.sin(leg_phase)
            calf = -1.6 + 0.1 * math.sin(leg_phase + 0.5)
            targets.extend([hip, thigh, calf])
        return targets
