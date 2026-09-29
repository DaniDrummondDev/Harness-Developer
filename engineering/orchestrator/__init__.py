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
"""

__version__ = "0.4.0"

HARNESS_NAME = "AI Engineering Harness"
