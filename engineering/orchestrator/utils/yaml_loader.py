"""Safe YAML parsing shared by the config loader and the Global Library (V1).

Only `yaml.SafeLoader` semantics (no Python object construction, nothing is
executed) plus one stricter rule: duplicate mapping keys are rejected instead
of silently keeping the last value.
"""

from __future__ import annotations

from typing import Any

import yaml


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of silently overriding."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key '{key}'", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_yaml(text: str) -> Any:
    """Parse `text` safely. Raises `yaml.YAMLError` on invalid YAML or duplicate keys."""
    return yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
