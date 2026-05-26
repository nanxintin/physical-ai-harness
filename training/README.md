# World Model Self-Evolution Pipeline

A closed-loop system where a robot autonomously discovers new skills by learning a world model from interaction data, imagining skill outcomes, and validating them in simulation.

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │         Self-Evolution Loop                  │
                    │  (evolution_loop.py · EvolutionConfig)       │
                    └──────────────────┬──────────────────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
┌─────────────────┐        ┌────────────────────┐       ┌────────────────────┐
│  World Model    │        │  Imagination       │       │  Skill Synthesis   │
│  (world_model.py)│        │  (imagination.py)  │       │  (skill_synthesis.py)│
│                 │        │                    │       │                    │
│  Transformer    │◀───────│  Rollout across    │◀──────│  LLM (Claude) or   │
│  ~2M params     │        │  random scenarios  │       │  rule-based compose │
│  state+contact  │        │  success/safety    │       │  from primitives    │
└────────┬────────┘        └────────────────────┘       └────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Adapter Layer (PyBullet / MuJoCo / Synthetic)                  │
│  Collects (state, action, next_state, contact) transitions      │
└─────────────────────────────────────────────────────────────────┘
```

### Cycle: Explore → Model → Imagine → Discover → Validate → Deploy

| Phase | What happens | Module |
|-------|-------------|--------|
| **Explore** | Random/curiosity-driven actions collect transitions | `SelfEvolutionLoop._explore()` |
| **Model** | Train world model on all collected transitions | `WorldModelTrainer` |
| **Imagine** | Rollout skill candidates through world model | `ImaginationValidator` |
| **Discover** | Propose new skills (LLM or rule-based composition) | `SkillSynthesizer` |
| **Validate** | Test skills passing imagination in real simulator | `SelfEvolutionLoop._validate_real()` |
| **Deploy** | Promote validated skills to the skill library | `SkillLibrary.add_learned()` |

## Module Overview

| File | Description |
|------|-------------|
| `world_model.py` | Structured World Model (Transformer) predicting `(state_t, action_t) → (state_{t+1}, contact, progress)` |
| `imagination.py` | Validates skill candidates via multi-scenario world model rollouts |
| `skill_synthesis.py` | LLM-driven or rule-based skill proposal from primitives |
| `evolution_loop.py` | Orchestrates the full self-evolution cycle |
| `configs/world_model.yaml` | Hyperparameter configuration |

## Quick Start

### Synthetic Demo (no GPU / simulator required)

```bash
# From project root
python -m scripts.run_mvp1                    # 3 cycles, ~10s
python -m scripts.run_mvp1 --cycles 5         # 5 cycles
```

### PyBullet Demo (requires pybullet)

```bash
pip install pybullet numpy Pillow
python -m scripts.run_mvp1 --real --cycles 5
```

### LLM-driven Skill Synthesis (requires Anthropic API key)

```bash
export ANTHROPIC_API_KEY="your-key"
# Set use_llm=True in config or code
```

## Running Tests

```bash
# Unit tests for the full pipeline
pytest tests/test_world_model.py -v

# Real integration tests (require simulators installed)
pytest tests/test_pybullet_real.py -v   # PyBullet arm
pytest tests/test_sumo_real.py -v       # SUMO traffic
pytest tests/test_mqtt_real.py -v       # MQTT IoT
```

## Experiment Results

Results are stored in `data/evolution_*/`. Each run produces:

```
data/evolution_llm/
├── cycle_000/
│   ├── world_model.pt          # Model checkpoint
│   ├── metrics.json            # WM eval metrics
│   ├── skill_library.json      # Skills at this cycle
│   └── data_stats.json         # Transition dataset stats
├── cycle_001/
│   └── ...
└── evolution_report.json       # Full run summary
```

### Key Metrics (evolution_llm, 5 cycles)

| Metric | Cycle 0 | Cycle 2 (best) | Cycle 4 (final) |
|--------|---------|----------------|-----------------|
| Mean state error | 0.0044 | 0.00072 | 0.0020 |
| Contact accuracy | 100% | 100% | 100% |
| Joint error (rad) | 0.0050 | 0.00062 | 0.0024 |
| EE error (m) | 0.0038 | 0.0011 | 0.0011 |
| Skill library size | 6 | 10 | 16 |
| Total interactions | 772 | 2385 | 4001 |

### Learned Skills

The system autonomously discovered: `pick_up_object`, `place_object_at_target`, `stack_block`, `push_object_to_target`, `sweep_object_to_goal`, and variations with different parameter strategies.

## Configuration

See `configs/world_model.yaml` for all hyperparameters:

- **World Model**: 11-dim state (Franka), 16-dim action, 256 hidden, 4-layer Transformer
- **Training**: lr=3e-4, batch=64, 30 epochs/cycle
- **Imagination**: 30 scenarios, 0.7 success threshold, 0.95 safety threshold
- **Evolution**: 5 cycles, 50 exploration episodes/cycle

## Design Decisions

- **Structured state** (joint angles + EE + objects) instead of pixel-level prediction for fast imagination rollouts
- **Uncertainty estimation** via ensemble disagreement to guide exploration and flag low-confidence predictions
- **Safety gating** in imagination: skills must pass both success AND safety thresholds before real validation
- **Incremental data**: world model trains on ALL accumulated transitions, not just current cycle
