"""AI Engineering Harness — engineering control plane.

V0 (Project Foundation): CLI, declarative configuration, logging,
subprocess/filesystem helpers and the `doctor` command.
V0.1 (Mode Foundation): Interactive/Autonomous modes, the normalized
`EngineeringRequest` contract, input normalization and request admission.
V0.2 (Provider Abstraction): LLMProvider / DecisionProvider contracts,
provider registry, model resolution from YAML and offline fake adapters.
"""

__version__ = "0.2.0"

HARNESS_NAME = "AI Engineering Harness"
