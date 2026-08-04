# Vendored engine-contract artefacts — DO NOT EDIT

These two files are copied verbatim from the `MagicStrategy_EngineKnowledge` package
delivered by the knowledge team. They are the contract this engine is measured against.

| File | Version | sha256 (first 16) |
|---|---|---|
| `RULE_REGISTRY.json` | 1.2.0 | `d85f979078815202` |
| `TELEMETRY_SCHEMA.json` | v1.1.0 | `1364ab11ae0703e7` |

## Why they are vendored rather than fetched

The contract requires the registry to be loaded **at build time, pinned by version, never
fetched at runtime** — rule ids are the join key for conformance and for the learning loop,
so a registry that could change under a running engine would make stored telemetry
un-auditable after the fact.

Vendoring also means CI can check our code against the exact registry the records were
emitted under, which is the whole point of `engine.rule_registry_version`.

## Editing these is a contract change, not a code change

If a rule looks wrong, that is a conversation with the knowledge team, not a local fix. A
local edit would make our telemetry claim conformance to a registry nobody else has.

`tests/unit/test_telemetry_contract.py` asserts the versions and hashes above. It fails if either file
changes, **including** when a legitimately updated package is dropped in — that failure is
the prompt to review the diff, re-run the conformance suite and update the pins
deliberately.

## Known version skew in the source package

`RULE_REGISTRY.json` is **1.2.0**; every prose document in the delivered package, and this
schema, are **v1.1.0** — written before a triage that cleared all 8 DEFECT rules and moved
20 rules from OPEN to READY.

**The registry is authoritative.** See `MAGIC_STRATEGY_INTEGRATION.md` §2.1. Salim has been
asked to regenerate the v1.1.0 documents; until then, any count quoted in the package's prose
is stale and this schema may lag the registry.
