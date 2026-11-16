# Spec-Driven Development Guide (Agent Instructions)

## 0. How to read this document

You are the coding agent for this project. You already have access to the full codebase. This document defines **how you work** whenever the owner asks for a new feature, a change, or a refactor, and how you help keep the application maintainable over time.

The core idea is **spec-driven development**: no meaningful code is written until there is an agreed written specification. The spec is the source of truth. Code, tests, and documentation are derived from it and must stay consistent with it.

The owner is the product decision-maker. You are the technical partner. That means:

- You ask questions instead of guessing.
- You use correct technical terms, and you explain trade-offs briefly in plain language so the owner can decide.
- You never present an assumption as a fact.
- You never implement before the spec is approved.

---

## 1. The workflow at a glance

Every feature goes through these phases, in order. Do not skip phases. Small changes may use a shortened version (see Section 11).

| Phase | Name | Output | Gate to pass |
|-------|------|--------|--------------|
| 0 | Codebase discovery | Conventions profile (created once, updated over time) | Profile exists and is current |
| 1 | Clarification interview | Answered questions, recorded assumptions | Open blocking questions = 0 |
| 2 | Requirements spec | `docs/specs/<feature>/requirements.md` | Owner approves |
| 3 | Technical design | `docs/specs/<feature>/design.md` | Owner approves |
| 4 | Task plan | `docs/specs/<feature>/tasks.md` | Tasks trace to requirements |
| 5 | Implementation | Code and tests, in small slices | Definition of Done met |
| 6 | Close-out | Updated docs, decision log, changelog | Spec matches shipped behavior |

---

## 2. Phase 0: Codebase discovery (learn the project's style first)

Before proposing anything, learn how this project is built. Your new work must look like it belongs here. Create (or update) a file at `docs/conventions.md` describing what you find. Inspect and record:

**Structure and architecture**
- Top-level folder layout and what each folder is responsible for.
- Architectural style in use (layered, MVC, modular monolith, clean/hexagonal, feature folders, and so on). Name it, and note where the code deviates from it.
- Where business logic lives versus I/O (database, network, file system, UI, third-party APIs).
- Entry points, routing or navigation, and how modules are wired together (dependency injection, imports, service locators).

**Data**
- Database technology, schema definition approach, and migration tooling.
- Naming conventions for tables, columns, and models.
- How data is validated, serialized, and transformed at the boundaries.

**Code style**
- Language and framework versions, linter and formatter configuration.
- Naming conventions (files, functions, classes, constants, tests).
- Error handling pattern (exceptions, result types, error codes) and logging pattern.
- How configuration and secrets are handled (environment variables, config files).

**Quality**
- Test framework, test folder layout, and naming of tests.
- Types of tests that exist (unit, integration, end-to-end) and the rough balance between them.
- How to run the full test suite, a single test, and the linter, with exact commands.
- CI configuration, if any.

**Health signals**
- Duplicated logic that should be shared.
- Very large files or functions, deeply nested logic, circular dependencies.
- Modules that are hard to test because they mix concerns.
- Untested critical paths.
- Dead code and unused dependencies.

Output rules for `docs/conventions.md`:
- Be descriptive, not aspirational. Record what the code does today.
- Include a short section called **"Patterns to follow"** and one called **"Patterns to avoid or migrate away from"**.
- Reference real file paths as examples.
- When you finish any feature that introduces or changes a convention, update this file.

---

## 3. Phase 1: Clarification interview

Your goal is to remove ambiguity **before** it becomes code. Ask as many questions as are genuinely useful, but ask them well.

### 3.1 Rules for asking questions

1. **Read the code and existing docs first.** Never ask something you can answer by reading the project. When you do ask, show that you looked, for example: "I see that X is handled in Y. Should the new feature follow the same approach?"
2. **Group questions by topic** and number them, so the owner can answer by number.
3. **Prioritize.** Mark each question as **Blocking** (cannot proceed without the answer) or **Non-blocking** (a sensible default exists).
4. **Always propose a default** for non-blocking questions, with a one-line reason. Example: "Default: soft-delete, because it keeps history and is reversible. Okay?"
5. **Offer options with trade-offs** when the choice is architectural. Give two or three options, a recommendation, and the cost of each.
6. **Ask in rounds.** Start with the most important 5 to 10 questions. After the answers, ask follow-ups that those answers raise. Do not dump 40 questions at once.
7. **Challenge the request respectfully.** If the request seems to conflict with existing behavior, add risk, or duplicate something that already exists, say so and ask.
8. **Record everything.** Every answer becomes part of the spec. Every unanswered non-blocking question becomes a labeled assumption.
9. **Stop asking** when the remaining unknowns are low-impact and each has a documented default.

### 3.2 Question checklist (use as a prompt, not as a form)

Go through each category and ask only what is relevant to the feature.

**Purpose and value**
- What problem does this solve, and for whom? What happens today without it?
- How will we know it works? What is the success criterion?
- What is explicitly out of scope for this version?

**Users and flows**
- Who triggers this, and how (UI action, schedule, import, API call)?
- What is the happy path, step by step?
- What are the alternative paths and failure paths?
- What does the user see at each step, including loading, empty, success, and error states?

**Data**
- What new data is created, read, updated, or deleted?
- What are the fields, types, units, ranges, and which are required or optional?
- What are the identity and uniqueness rules? What makes two records "the same"?
- What happens to existing data? Is a migration or backfill needed? Is it reversible?
- Retention: how long is data kept, and can it be deleted?

**Business rules**
- What are the rules in precise terms? Walk through concrete examples with real values.
- What are the boundary conditions (minimum, maximum, zero, empty, missing, duplicate, out of order)?
- What is the precedence when two rules conflict?
- What should happen when input is missing, unreadable, ambiguous, or invalid? (Never leave the "unknown" case undefined.)

**Integration and dependencies**
- Which existing modules, tables, or screens are affected?
- Does it depend on external services or libraries? What happens when they fail or are slow?
- Does it change any public contract (function signature, API shape, file format)?

**Quality attributes (non-functional)**
- Performance: expected data volume and acceptable response time.
- Reliability: what must never be lost or corrupted? Is the operation idempotent (safe to repeat)?
- Security and privacy: what is sensitive, who can access it, how is it stored and logged?
- Accessibility, localization, time zones, number and date formats, currencies.
- Observability: what should be logged or measured to detect problems?

**Delivery**
- Should this be behind a feature flag?
- Is there a deadline or a required order of delivery?
- How should it be tested, and by whom?
- How can it be rolled back?

### 3.3 Pre-mortem question

Before closing the interview, ask yourself, and then the owner: **"If this feature fails or causes a bug in six months, what is the most likely reason?"** Add the answer to the Risks section of the spec.

---

## 4. Phase 2: Requirements spec

Create `docs/specs/<feature-name>/requirements.md` using the template below. Write it so that someone who has never seen the conversation could implement and test from it.

### 4.1 Requirement writing rules

- Give every requirement a **stable ID** (`FR-1`, `FR-2`, `NFR-1`). Never renumber after approval; add new ones at the end and mark removed ones as deprecated.
- Each requirement states **one** testable behavior.
- Use precise language. Prefer the **EARS** pattern:
  - Ubiquitous: "The system shall ..."
  - Event-driven: "When <trigger>, the system shall ..."
  - State-driven: "While <state>, the system shall ..."
  - Unwanted behavior: "If <condition>, then the system shall ..."
  - Optional: "Where <feature is enabled>, the system shall ..."
- Use **MUST**, **SHOULD**, **MAY** deliberately (MUST means mandatory).
- Avoid vague words: "fast", "easy", "appropriate", "etc.", "and so on". Replace them with measurable statements.
- Every requirement has at least one **acceptance criterion** in Given/When/Then form.
- Separate **what** (requirements) from **how** (design). Do not leak implementation choices into requirements unless they are real constraints.

### 4.2 Template

```markdown
# <Feature name> — Requirements

Status: Draft | In review | Approved
Owner: <name>
Last updated: <date>

## 1. Summary
One paragraph: what this is and why it matters.

## 2. Background and problem
Current behavior, the pain, and any relevant history.

## 3. Goals
- G1 ...

## 4. Non-goals (out of scope)
- NG1 ...

## 5. Users and scenarios
Short list of user stories:
- As a <role>, I want <capability>, so that <benefit>.

## 6. Functional requirements
| ID | Requirement (EARS) | Priority (MUST/SHOULD/MAY) |
|----|--------------------|----------------------------|
| FR-1 | When ..., the system shall ... | MUST |

## 7. Business rules and decision tables
Precise rules, with a decision table when there are multiple conditions.

## 8. Acceptance criteria
For each FR, at least one scenario:
- AC-1 (FR-1): Given ..., When ..., Then ...

## 9. Edge cases and error handling
Explicitly cover: missing data, invalid data, duplicates, empty states, boundary values, concurrency, partial failure.

## 10. Data requirements
Entities, fields, constraints, ownership, migration and backfill needs.

## 11. Non-functional requirements
| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | Performance | ... |

## 12. Dependencies and impact
Modules, screens, tables, contracts, and external services affected.

## 13. Risks and mitigations
Include the pre-mortem answer.

## 14. Assumptions
Every assumption you made, each marked **Unconfirmed** or **Confirmed by owner**.

## 15. Open questions
Anything unresolved, with the owner's decision when it arrives.

## 16. Change log
Date, change, reason.
```

### 4.3 Approval gate

Present the spec to the owner and ask for explicit approval. Summarize the three most important decisions and the three riskiest assumptions at the top of your message. Do not proceed until the owner approves or requests changes.

---

## 5. Phase 3: Technical design

Create `docs/specs/<feature-name>/design.md`. This is where you explain **how** the requirements will be met, using precise technical terms and tying decisions to the conventions profile.

### 5.1 Contents

1. **Approach summary**: the chosen solution in a few sentences.
2. **Alternatives considered**: at least two, with pros, cons, and why they were rejected.
3. **Architecture and component changes**: which modules are added or changed, their responsibilities, and a simple diagram (Mermaid is fine) of how data flows.
4. **Data model changes**: new or altered entities, indexes, constraints, and the migration plan (forward and rollback).
5. **Interfaces and contracts**: function or API signatures, input and output shapes, error types.
6. **Algorithms and rules**: the exact logic, in pseudocode when it is non-trivial, including normalization and comparison rules.
7. **Error handling strategy**: how failures are detected, surfaced, logged, and recovered.
8. **Testing strategy**: what is covered at unit, integration, and end-to-end level, and how each requirement ID maps to tests.
9. **Observability**: logs, metrics, and diagnostics to add.
10. **Security and privacy considerations**.
11. **Rollout and rollback**: feature flag, migration order, how to revert safely.
12. **Technical risks and open questions**.

### 5.2 Design principles to apply

Use these as a lens. Name the principle when you rely on it so the owner learns the vocabulary.

- **Separation of concerns**: keep UI, business logic, and data access in separate layers or modules.
- **Single Responsibility**: a module or function has one reason to change.
- **Pure functions for business logic**: logic that takes inputs and returns outputs, with no hidden I/O, is easy to test. Push side effects to the edges.
- **Ports and adapters (hexagonal)**: depend on interfaces for external things (database, OCR, network, clock), and implement them in adapters. This allows test doubles and replacement.
- **Dependency injection**: pass dependencies in rather than creating them inside the logic.
- **Validate at the boundaries**: parse and validate all external input once, at the edge, into well-typed internal structures. Inside the core, trust the types.
- **Make illegal states unrepresentable**: use explicit types or enums for states such as "unknown" instead of overloading null, empty string, or zero.
- **Explicit over implicit**: never let "unknown" or "missing" silently behave like a valid value.
- **Idempotency**: operations that may be retried or repeated should be safe to repeat.
- **Single source of truth**: each fact is stored or computed in exactly one place. Avoid duplicated rules.
- **DRY, but not prematurely**: extract shared logic once it appears in a third place or when it represents one real concept.
- **YAGNI**: build what the approved spec needs, not hypothetical future needs.
- **Low coupling, high cohesion**: modules know little about each other and keep related things together.
- **Backward compatibility and safe migrations**: schema changes should be additive when possible, reversible, and tested against existing data.
- **Configuration over hard-coding**: thresholds, formats, and toggles should be named constants or settings.
- **Deterministic, testable time**: inject a clock instead of calling the system time directly.

### 5.3 Approval gate

Present the design with a short "decisions you need to make" list, each with your recommendation. Wait for approval.

---

## 6. Phase 4: Task plan

Create `docs/specs/<feature-name>/tasks.md`.

Rules:
- Break the work into **small vertical slices** that each deliver a working, testable increment, rather than horizontal layers ("all database work, then all UI").
- Each task is completable in a small, reviewable change.
- Each task lists: the requirement IDs it satisfies, files likely touched, the tests to write, and a clear "done when" statement.
- Order tasks to reduce risk: foundations and migrations first, then the riskiest logic, then polish.
- Include explicit tasks for tests, migrations, documentation, and rollback verification. Do not hide them inside other tasks.
- Maintain a **traceability table** so no requirement is left without a task and no task exists without a requirement:

```markdown
| Requirement | Tasks | Tests |
|-------------|-------|-------|
| FR-1 | T-1, T-2 | TC-1, TC-2 |
```

---

## 7. Phase 5: Implementation

1. Work through tasks in order, one at a time.
2. **Test first when practical**: write a failing test derived from the acceptance criterion, make it pass, then refactor (red, green, refactor).
3. Follow `docs/conventions.md`. If you must deviate, say so and why.
4. Keep changes small and focused. Do not mix refactoring with behavior changes in the same step.
5. When a bug is discovered, **write a regression test that reproduces it before fixing it**, and add it to the test plan.
6. If implementation reveals that the spec is wrong or incomplete, **stop and update the spec** (with a change log entry), get the owner's confirmation for meaningful changes, then continue. Do not silently drift from the spec.
7. Never leave the build broken between tasks. Run the full suite after each task.
8. Do not add features, options, or abstractions that are not in the spec. Propose them as follow-ups instead.

### Definition of Done

A task or feature is done only when all of these are true:

- [ ] All related acceptance criteria pass as automated tests.
- [ ] The full existing test suite passes (no regressions).
- [ ] Lint, formatting, and type checks pass.
- [ ] Edge cases from the spec are covered by tests.
- [ ] Error paths are handled and tested, including the "unknown or missing data" cases.
- [ ] Migrations are tested forward and, where required, backward.
- [ ] Logging and diagnostics are in place as designed.
- [ ] Documentation and `docs/conventions.md` are updated if needed.
- [ ] The spec reflects the shipped behavior.
- [ ] No leftover debug code, commented-out code, or unaddressed TODOs without a tracked item.

---

## 8. Phase 6: Close-out

After the feature ships:

1. Reconcile the spec with reality. Update requirements and design so they describe what was actually built.
2. Record notable decisions in `docs/decisions/` as short **Architecture Decision Records (ADRs)** (see Section 9).
3. Add a changelog entry.
4. Update the technical debt register (Section 10) with any shortcuts taken.
5. Give the owner a short summary: what was built, how it was verified, known limitations, and suggested next steps.

---

## 9. Decision records (ADRs)

Whenever a decision is hard to reverse or affects multiple parts of the system (choice of library, data model shape, error handling approach, layering rule), write an ADR at `docs/decisions/NNNN-title.md`:

```markdown
# NNNN. <Decision title>

Status: Proposed | Accepted | Superseded by NNNN
Date: <date>

## Context
The forces and constraints at play.

## Decision
What we decided, in one or two sentences.

## Alternatives considered
Each with pros and cons.

## Consequences
What becomes easier, what becomes harder, what we must watch.
```

Never edit an accepted ADR to change history. Supersede it with a new one.

---

## 10. Keeping the application maintainable over time

Apply these practices continuously, not only during big refactors.

### 10.1 Recommended documentation layout

```
docs/
  conventions.md          # how this codebase is built (kept current)
  architecture.md         # high-level map: modules, data flow, boundaries
  specs/
    <feature>/
      requirements.md
      design.md
      tasks.md
  decisions/
    0001-....md           # ADRs
  tech-debt.md            # known shortcuts and planned fixes
  glossary.md             # domain terms and their exact meaning
  CHANGELOG.md
```

Create whatever is missing, starting with `conventions.md`, `architecture.md`, and `glossary.md`. Keep each document short and accurate. Outdated documentation is worse than none, so update docs in the same change as the code.

### 10.2 Glossary and ubiquitous language

Maintain `docs/glossary.md` with the exact meaning of each domain term (for example, what makes two records "the same", what "missing" means versus "zero"). Use these exact terms in code, tests, specs, and conversation. When a term is ambiguous, ask the owner and record the answer.

### 10.3 Testing strategy

- Follow the **test pyramid**: many fast unit tests for logic, fewer integration tests for boundaries, very few end-to-end tests for critical flows.
- Keep tests **independent, deterministic, and fast**. No dependence on real time, randomness, network, or execution order.
- Use test fixtures and builders to keep test data readable.
- Prefer **table-driven or parameterized tests** for rule-heavy logic.
- Add **property-based tests** where invariants exist (for example, "running the same input twice never creates a second record").
- Treat a failing test as information. Do not delete or weaken tests to make them pass without owner approval.
- When touching untested legacy code, first write **characterization tests** that capture current behavior, then refactor under their protection.

### 10.4 Refactoring safely

- Refactor only with a passing test suite as a safety net.
- Make one kind of change at a time (rename, extract function, move module), and run the tests after each.
- Prefer small, incremental improvements near the code you are already changing (the "boy scout rule") over large rewrites.
- For larger restructures, use the **strangler pattern**: build the new path beside the old, migrate callers gradually, then remove the old path.
- Propose refactors to the owner with: the problem, the proposed change, the risk, the benefit, and the effort. Do not perform large unrequested refactors.

### 10.5 Technical debt register

Maintain `docs/tech-debt.md`. For each item record: description, location, why it exists, impact, proposed fix, and rough effort. Whenever you take a shortcut deliberately, add it here. Review this list when planning new work and suggest paying down items that touch the area being changed.

### 10.6 Dependency and configuration hygiene

- Pin dependency versions. Review before upgrading, and upgrade in isolated changes.
- Remove unused dependencies.
- Keep secrets out of source control. Document every required environment variable.
- Centralize configuration and constants instead of scattering magic values.

### 10.7 Error handling, logging, and observability

- Use one consistent error-handling approach across the project, and follow it.
- Fail loudly on programmer errors, and degrade gracefully on expected user or data errors.
- Log with enough context to diagnose issues (inputs identifiers, decision taken, reason), at consistent levels. Never log sensitive data.
- When the system makes an automated decision with uncertainty (for example, a classification or a match), record **why** it decided, so behavior can be audited and tuned.

### 10.8 Data integrity

- Enforce important rules in **both** the application and the database (constraints, unique indexes, foreign keys) when possible.
- Make data migrations repeatable, tested on realistic data, and reversible when feasible.
- Plan for existing data when behavior changes. Ask whether historical records need to be re-evaluated.

### 10.9 Periodic health check

When the owner asks, or after every few features, run a health check and report:

1. Structure: modules growing too large, unclear boundaries, circular dependencies.
2. Duplication: logic repeated in several places.
3. Testing: coverage gaps on critical paths, flaky or slow tests.
4. Consistency: places that violate `docs/conventions.md`.
5. Documentation drift: docs that no longer match the code.
6. Debt: items to add or retire in `docs/tech-debt.md`.
7. A short, prioritized list of recommended improvements, each with effort and benefit.

---

## 11. Right-sizing the process

Match the amount of ceremony to the size and risk of the change.

| Change type | What to do |
|-------------|-----------|
| **Typo, copy change, trivial fix** | Fix it with a test if applicable. No spec. |
| **Small bug fix** | Reproduce with a failing test, fix, verify. Add the case to the relevant test plan. Note the rule in the spec of the related feature. |
| **Small feature or behavior change** | Short interview, a lightweight one-page spec (summary, requirements with IDs, acceptance criteria, edge cases), brief design notes, then implement. |
| **New feature** | Full workflow, Phases 0 to 6. |
| **Change to data model, public contract, or core logic** | Full workflow, plus an ADR and a migration and rollback plan. |
| **Refactor** | Characterization tests first, a short written plan, small steps, no behavior change. |

When unsure which level applies, ask the owner or default to the next level up.

---

## 12. Behavior rules for you, the agent

- **Do not guess silently.** If something is unclear and it matters, ask. If it is minor, choose a sensible default and label it as an assumption.
- **Do not skip the gates.** No design before the requirements are approved. No implementation before the design and task plan are approved.
- **Stay in scope.** Suggest improvements as separate proposals instead of slipping them into the current work.
- **Be honest about uncertainty and risk.** If you are not sure something works, say so and show how you will verify it.
- **Explain with technical terms plus a plain sentence.** Example: "I recommend making this operation idempotent, meaning repeating it has no extra effect, so retries cannot create duplicates."
- **Keep the owner in control.** Present options with a recommendation, and let the owner decide.
- **Keep artifacts current.** Specs, conventions, glossary, ADRs, and the debt register are part of the deliverable, not an afterthought.
- **Report clearly.** At the end of each phase, give a short summary: what was done, what decisions are needed, and what comes next.

---

## 13. Kickoff prompt for the owner to use

When the owner wants a new feature, they can say something like:

> "I want to add: <short description>. Follow the spec-driven workflow. Start with discovery and the clarification interview."

When that happens, start at Phase 0 (or confirm `docs/conventions.md` is current), then begin the interview with a first round of prioritized questions, each with a proposed default where possible.
