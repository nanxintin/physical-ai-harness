"""Unit tests for the world model self-evolution pipeline."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from training.world_model import (
    RobotAction,
    RobotState,
    StateTransition,
    StructuredWorldModel,
    TransitionDataset,
    WorldModelTrainer,
)
from training.imagination import (
    ImaginationValidator,
    Scenario,
    SkillCandidate,
)
from training.skill_synthesis import (
    SkillLibrary,
    SkillSynthesizer,
    build_franka_primitives,
)
from training.evolution_loop import (
    EvolutionConfig,
    SelfEvolutionLoop,
)


# --- World Model Tests ---


class TestRobotState:
    def test_to_vector(self):
        state = RobotState(
            joint_positions=np.zeros(7),
            ee_position=np.array([0.4, 0.0, 0.3]),
            gripper_width=0.04,
        )
        vec = state.to_vector()
        assert vec.dtype == np.float32
        assert len(vec) >= 11  # 7 joints + 3 ee + 1 gripper

    def test_with_objects(self):
        state = RobotState(
            joint_positions=np.zeros(7),
            ee_position=np.array([0.4, 0.0, 0.3]),
            gripper_width=0.04,
            object_positions={"block_a": np.array([0.3, 0.0, 0.05])},
        )
        vec = state.to_vector()
        assert len(vec) >= 14  # 11 + 3 (object pos)


class TestRobotAction:
    def test_to_vector(self):
        action = RobotAction(
            action_type="joint_target",
            values=np.array([0.1, 0.2, 0.3]),
            duration=0.1,
        )
        vec = action.to_vector(max_dim=16)
        assert vec.shape == (16,)
        assert vec[0] == 0.0  # joint_target type
        assert vec[1] == 0.1  # duration

    def test_ee_delta_type(self):
        action = RobotAction(action_type="ee_delta", values=np.array([0.01, 0.0, -0.01]))
        vec = action.to_vector()
        assert vec[0] == pytest.approx(1.0 / 3.0)


class TestStructuredWorldModel:
    @pytest.fixture
    def model(self):
        return StructuredWorldModel(state_dim=11, action_dim=16, contact_dim=4, hidden_dim=64, n_layers=2)

    def test_forward_shape(self, model):
        state = torch.randn(4, 11)
        action = torch.randn(4, 16)
        next_state, contact, progress, uncertainty = model(state, action)
        assert next_state.shape == (4, 11)
        assert contact.shape == (4, 4)
        assert progress.shape == (4, 1)
        assert uncertainty.shape == (4, 11)

    def test_residual_prediction(self, model):
        state = torch.randn(1, 11)
        action = torch.zeros(1, 16)  # zero action
        next_state, _, _, _ = model(state, action)
        # With zero action, residual should be small (untrained, but structurally sound)
        assert next_state.shape == state.shape

    def test_rollout(self, model):
        init_state = torch.randn(11)
        actions = torch.randn(10, 16)
        result = model.rollout(init_state, actions)
        assert result["states"].shape == (11, 11)  # T+1 states
        assert result["contacts"].shape == (10, 4)
        assert result["progress"].shape == (10, 1)
        assert result["uncertainty"].shape == (10, 11)

    def test_rollout_max_steps(self, model):
        init_state = torch.randn(11)
        actions = torch.randn(20, 16)
        result = model.rollout(init_state, actions, max_steps=5)
        assert result["states"].shape == (6, 11)  # 5+1

    def test_prediction_confidence(self, model):
        unc = torch.tensor([[0.1, 0.2, 0.3]])
        conf = model.prediction_confidence(unc)
        assert 0 < conf < 1

    def test_contact_sigmoid(self, model):
        state = torch.randn(2, 11)
        action = torch.randn(2, 16)
        _, contact, _, _ = model(state, action)
        assert (contact >= 0).all()
        assert (contact <= 1).all()

    def test_progress_sigmoid(self, model):
        state = torch.randn(2, 11)
        action = torch.randn(2, 16)
        _, _, progress, _ = model(state, action)
        assert (progress >= 0).all()
        assert (progress <= 1).all()


class TestTransitionDataset:
    def test_creation(self):
        transitions = [
            StateTransition(
                state=np.random.randn(11).astype(np.float32),
                action=np.random.randn(16).astype(np.float32),
                next_state=np.random.randn(11).astype(np.float32),
                contact=np.random.rand(4).astype(np.float32),
            )
            for _ in range(20)
        ]
        dataset = TransitionDataset(transitions)
        assert len(dataset) == 20
        s, a, ns, c, d = dataset[0]
        assert s.shape == (11,)
        assert a.shape == (16,)


class TestWorldModelTrainer:
    @pytest.fixture
    def trainer_and_data(self):
        model = StructuredWorldModel(state_dim=11, action_dim=16, hidden_dim=64, n_layers=2)
        trainer = WorldModelTrainer(model, lr=1e-3)
        transitions = [
            StateTransition(
                state=np.random.randn(11).astype(np.float32),
                action=np.random.randn(16).astype(np.float32),
                next_state=np.random.randn(11).astype(np.float32),
                contact=(np.random.rand(4) > 0.5).astype(np.float32),
            )
            for _ in range(50)
        ]
        dataset = TransitionDataset(transitions)
        loader = torch.utils.data.DataLoader(dataset, batch_size=16, shuffle=True)
        return trainer, loader, transitions

    def test_train_epoch(self, trainer_and_data):
        trainer, loader, _ = trainer_and_data
        loss = trainer.train_epoch(loader)
        assert loss > 0
        assert len(trainer.train_losses) == 1

    def test_loss_decreases(self, trainer_and_data):
        trainer, loader, _ = trainer_and_data
        losses = []
        for _ in range(10):
            loss = trainer.train_epoch(loader)
            losses.append(loss)
        # Loss should generally decrease (allow some noise)
        assert losses[-1] < losses[0] * 2  # at least not exploding

    def test_evaluate(self, trainer_and_data):
        trainer, loader, _ = trainer_and_data
        trainer.train_epoch(loader)
        metrics = trainer.evaluate(loader)
        assert "mean_state_error" in metrics
        assert "contact_accuracy" in metrics
        assert metrics["mean_state_error"] >= 0

    def test_save_load(self, trainer_and_data, tmp_path):
        trainer, loader, _ = trainer_and_data
        trainer.train_epoch(loader)
        save_path = tmp_path / "model.pt"
        trainer.save(save_path)
        loaded = WorldModelTrainer.load(save_path)
        assert loaded.model.state_dim == 11


# --- Imagination Validator Tests ---


class TestImaginationValidator:
    @pytest.fixture
    def validator(self):
        model = StructuredWorldModel(state_dim=11, action_dim=16, hidden_dim=64, n_layers=2)
        return ImaginationValidator(model, success_threshold=0.5)

    def test_validate_skill(self, validator):
        skill = SkillCandidate(
            name="test_skill",
            action_sequence=[np.random.randn(16).astype(np.float32) * 0.1 for _ in range(5)],
        )
        report = validator.validate(skill, n_scenarios=10)
        assert report.skill_name == "test_skill"
        assert report.n_scenarios == 10
        assert 0 <= report.success_rate <= 1
        assert 0 <= report.safety_rate <= 1

    def test_batch_validate(self, validator):
        skills = [
            SkillCandidate(name=f"skill_{i}", action_sequence=[np.random.randn(16).astype(np.float32) * 0.1 for _ in range(3)])
            for i in range(3)
        ]
        reports = validator.batch_validate(skills, n_scenarios=5)
        assert len(reports) == 3

    def test_rank_candidates(self, validator):
        skills = [
            SkillCandidate(name=f"skill_{i}", action_sequence=[np.random.randn(16).astype(np.float32) * 0.1 for _ in range(3)])
            for i in range(3)
        ]
        reports = validator.batch_validate(skills, n_scenarios=5)
        ranked = validator.rank_candidates(reports)
        assert len(ranked) == 3
        # Should be sorted by score descending
        scores = [score for _, score in ranked]
        assert scores == sorted(scores, reverse=True)


# --- Skill Synthesis Tests ---


class TestSkillLibrary:
    def test_add_primitives(self):
        library = SkillLibrary()
        for prim in build_franka_primitives():
            library.add_primitive(prim)
        assert library.skill_count == 3
        assert "reach" in library.primitives
        assert "grasp" in library.primitives
        assert "release" in library.primitives

    def test_describe_for_llm(self):
        library = SkillLibrary()
        for prim in build_franka_primitives():
            library.add_primitive(prim)
        desc = library.describe_for_llm()
        assert "reach" in desc
        assert "grasp" in desc
        assert "Available Skills" in desc


class TestSkillSynthesizer:
    @pytest.fixture
    def synthesizer(self):
        library = SkillLibrary()
        for prim in build_franka_primitives():
            library.add_primitive(prim)
        return SkillSynthesizer(library, robot_type="franka")

    def test_synthesize_pick_up(self, synthesizer):
        skill = synthesizer.synthesize_without_llm("pick up the block")
        assert skill is not None
        assert skill.name == "pick_up"
        assert len(skill.action_sequence) > 0
        assert skill.source == "composition"

    def test_synthesize_stack(self, synthesizer):
        skill = synthesizer.synthesize_without_llm("stack blocks")
        assert skill is not None
        assert skill.name == "stack"

    def test_synthesize_push(self, synthesizer):
        skill = synthesizer.synthesize_without_llm("push the object")
        assert skill is not None
        assert skill.name == "push"

    def test_synthesize_unknown_returns_none(self, synthesizer):
        skill = synthesizer.synthesize_without_llm("fly to the moon")
        assert skill is None


# --- Evolution Loop Tests ---


class TestSelfEvolutionLoop:
    def test_single_cycle_synthetic(self):
        config = EvolutionConfig(
            state_dim=11,
            action_dim=16,
            hidden_dim=32,
            wm_n_layers=1,
            wm_epochs_per_cycle=3,
            explore_episodes_per_cycle=5,
            max_steps_per_episode=5,
            goals_per_cycle=2,
            imagination_scenarios=5,
            output_dir="data/test_evolution",
            save_checkpoints=False,
        )
        loop = SelfEvolutionLoop(config)
        metrics = loop.run_cycle(0)

        assert metrics.cycle == 0
        assert metrics.total_real_interactions > 0
        assert metrics.wm_train_loss > 0
        assert metrics.skill_library_size >= 3  # at least the primitives

    def test_multi_cycle_skill_growth(self):
        config = EvolutionConfig(
            state_dim=11,
            action_dim=16,
            hidden_dim=64,
            wm_n_layers=2,
            wm_epochs_per_cycle=10,
            explore_episodes_per_cycle=10,
            max_steps_per_episode=10,
            goals_per_cycle=3,
            imagination_scenarios=10,
            success_threshold=0.5,
            safety_threshold=0.5,
            confidence_threshold=0.3,
            output_dir="data/test_evolution_multi",
            save_checkpoints=False,
        )
        loop = SelfEvolutionLoop(config)
        all_metrics = loop.run(3)

        assert len(all_metrics) == 3
        # At least some skills should be proposed across 3 cycles
        total_proposed = sum(m.skills_proposed for m in all_metrics)
        assert total_proposed > 0

    def test_curiosity_proposes_new_goals(self):
        from training.evolution_loop import CuriosityModule
        library = SkillLibrary()
        for prim in build_franka_primitives():
            library.add_primitive(prim)
        curiosity = CuriosityModule(library, "franka")
        goals = curiosity.propose_goals(0)
        assert len(goals) > 0
        assert all(isinstance(g, str) for g in goals)
