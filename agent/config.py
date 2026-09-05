"""Constants and tunables for the advisor agent.

Everything an operator might want to change lives here. Nothing in this module
imports from the rest of the agent, so it is safe to import anywhere.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Models
#
# PLACEHOLDER: no network calls are made anywhere in this package yet. These
# ids are recorded so the swap in `agent/llm.py` is a one-line change per role.
# --------------------------------------------------------------------------
ROUTER_MODEL = "claude-haiku-4-5-20251001"  # cheap classification
ADVISOR_MODEL = "claude-sonnet-5"           # the tool loop
EXPLAINER_MODEL = "claude-sonnet-5"         # answer object -> prose

MAX_TOOL_ITERATIONS = 8  # hard stop on the tool loop; a tier-3 ask needs ~5

# Local and hosted backends, selected by env var in devui. Measured tool-call
# accuracy on this repo's schemas at temperature 0:
#
#   qwen/qwen3.6-27b  (Groq)    5/5   sub-second when not rate limited
#   qwen3:8b          (Ollama)  4/4   10-30s on a laptop
#   llama3.1:8b       (Ollama)  4/4
#   llama3.2          (Ollama)  2/4   3B model
#   llama3            (Ollama)  0/4   no tool support at all
OLLAMA_MODEL = "qwen3:8b"
GROQ_MODEL = "qwen/qwen3.6-27b"

# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "crew-ops-advisor-dataset"
DATA_DIR = DATASET_DIR / "data"

# The dataset is a fixed week. Bare dates like "15 Sep" resolve into it.
SNAPSHOT_UTC = "2026-09-14T18:00:00Z"
WEEK_START = "2026-09-14"
WEEK_END = "2026-09-20"
DEFAULT_YEAR = 2026

# --------------------------------------------------------------------------
# Controlled vocabulary (derived from the dataset; see tests/test_entities.py,
# which asserts these still match what the JSON actually contains)
# --------------------------------------------------------------------------
STATIONS = frozenset({"BLR", "BOM", "CCU", "COK", "DEL", "GOI", "HYD", "MAA"})
AIRCRAFT = frozenset({"VT-DXA", "VT-DXB", "VT-DXC", "VT-DXD", "VT-DXE", "VT-DXF"})
AIRCRAFT_TYPES = frozenset({"A320", "ATR72"})
ROLES = ("Captain", "First Officer", "Senior Cabin Crew", "Cabin Crew")
CERT_TYPES = frozenset(
    {"dangerous_goods", "licence", "medical_class1", "recurrent_training"}
)

ALL_RULE_IDS = (
    "RULE-FDP-01",
    "RULE-DUTY-02",
    "RULE-FLT-03",
    "RULE-REST-04",
    "RULE-QUAL-05",
    "RULE-CERT-06",
    "RULE-BASE-07",
)

# --------------------------------------------------------------------------
# Retrieval
#
# The full exemplar corpus is 776 tokens, so it ships inside the cached system
# prompt rather than being retrieved. These knobs exist for the one corpus that
# does grow: the decision audit log. See DECISIONS.md #15.
# --------------------------------------------------------------------------
RETRIEVAL_K = 3
RETRIEVAL_MIN_SIMILARITY = 0.5  # below this, pass no exemplar at all
EMBED_DIM = 384                 # all-MiniLM-L6-v2, when a real embedder lands

# --------------------------------------------------------------------------
# Verifier
# --------------------------------------------------------------------------
# Numbers below this are prose ("all 7 rules", "the 2 options") rather than
# claims about the world, so the verifier does not demand a source for them.
VERIFIER_NUMERIC_FLOOR = 10.0
VERIFIER_FLOAT_TOLERANCE = 0.01
