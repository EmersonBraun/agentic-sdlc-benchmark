# Tasks

Tasks are English-only, frozen, and generated from private manifests before collection.

The public task package contains issue text, task identifiers, category, product, difficulty class, and post-collection release metadata. Canonical requirements, oracle truth tables, reference solutions, and hidden tests remain private until collection ends.

The pilot task package starts with [`public/pilot_greenfield_service_readiness.md`](public/pilot_greenfield_service_readiness.md) and its public manifest. It is a benchmark input, not a completed implementation.

The corresponding GitHub Issue and source/body hashes are recorded in
[`public/issue-index-v1.1.json`](public/issue-index-v1.1.json). GitHub adds one
trailing newline to the API body representation; the index records both hashes
so the issue remains externally verifiable without changing the frozen task
source.

The study PRD is [`../docs/prd-v1.1.md`](../docs/prd-v1.1.md) and is tracked as
the study contract, separately from executable benchmark tasks.
