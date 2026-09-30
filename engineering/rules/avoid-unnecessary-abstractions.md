---
version: 1
id: avoid-unnecessary-abstractions
type: rule
name: Avoid unnecessary abstractions
description: Introduce an interface, factory, layer or generic only when it has a current, real consumer.
tags: [design, simplicity]
applies_to:
  always: true
---
# Rule: Avoid unnecessary abstractions

**Instruction.** Do not add an interface, base class, factory, plugin point, configuration
option or generic parameter until there is a real consumer that needs it now. One
implementation does not need an interface unless a test fake or a boundary requires it.

**Verifiable by**
- every new abstraction has at least one production consumer in the same change;
- every new configuration field is read by code in the same change;
- no "for future use" code paths.

**Why.** Speculative abstractions add indirection and maintenance cost and usually guess
the future wrong. Prepare for evolution by keeping code simple, not by building it early.
