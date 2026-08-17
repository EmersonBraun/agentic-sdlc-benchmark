# Common SDLC Contract

```text
Issue intake
→ Requirements discovery
→ Requirements approval
→ Technical planning
→ Task decomposition
→ Implementation
→ Local testing
→ Pull request
→ CI/QA
→ Specialized review
→ Review/fix loop
→ Final review
→ Merge
→ Documentation and memory update
```

## Requirements output

- clarified PRD
- functional and non-functional requirements
- acceptance criteria
- assumptions and constraints
- ambiguity log
- requirements traceability matrix
- oracle questions and answers

## Planning output

- implementation plan
- subtasks linked to requirements
- architecture decision records
- impact analysis
- migration and test strategies
- risks and rejected alternatives

## Pull request contract

Every PR includes the change summary, requirements covered, decisions, tests, risks, migrations, operational impact, security checklist, and issue link.

## Review contract

Reviews cover functionality, architecture, security, tests, regressions, scope, and unnecessary changes. Findings require severity, evidence, location, and recommendation. A maximum of three review/fix cycles is allowed.

## Ambiguity handling

Agents must record ambiguities and ask the deterministic stakeholder oracle. They may not silently invent requirements.
