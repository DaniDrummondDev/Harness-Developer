"""AI Engineering Harness — engineering control plane.

V0 (Project Foundation): CLI, declarative configuration, logging,
subprocess/filesystem helpers and the `doctor` command.
V0.1 (Mode Foundation): Interactive/Autonomous modes, the normalized
`EngineeringRequest` contract, input normalization and request admission.
V0.2 (Provider Abstraction): LLMProvider / DecisionProvider contracts,
provider registry, model resolution from YAML and offline fake adapters.
V0.3 (Memory Foundation): MemoryProvider contract, Mem0 self-hosted adapter,
scopes, lineage, safe ingestion policy and the `memory` CLI group.
V0.4 (Decision Foundation): Jev (TypeSafe) DecisionProvider adapter, typed
decisions (choice/score/probability/confidence), configurable thresholds,
fallback contract, decision telemetry and the `decision` CLI group.
V1 (Global Library): versioned skills, guidelines, policies, rules and
specialties owned by the installation; typed loading/validation, deterministic
resolution against the project profile, the `library` CLI group and a
`library` doctor check.
V1.1 (Context Candidate Discovery): `orchestrator/context/` lists sources that
may be relevant to a request (library, instructions, ADRs, docs, repository
hints, memory) as typed, deduplicated, provenance-carrying candidates — no
classification, scoring or budget; `context discover` and a `context` doctor
check.
"""

__version__ = "1.1.0"

HARNESS_NAME = "AI Engineering Harness"
