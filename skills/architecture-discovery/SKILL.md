---
name: architecture-discovery
description: Discovers what runtime units trigger a service, lambda, worker, script, or job upstream, what downstream systems or execution units it triggers, and what evidence supports each relationship - so agents can trace distributed system flow in either direction or both.
license: MIT
---

# Upstream / Downstream Discovery

## Keywords

upstream, downstream, trigger, triggers, caller, callers, consumer, consumers, publisher, publishers, invoked by, invokes, what calls this, what triggers this, what does this call, what does this trigger, trace flow, map dependencies, event source, event consumer, runtime dependency, lambda trigger, job trigger, worker trigger, service trigger, system flow

## When to Use This Skill

Use this skill when a user wants to understand the runtime neighborhood around a deployable execution unit, including:
- What triggers or invokes a service, lambda, worker, script, handler, or job
- What downstream systems, jobs, events, or workflows it triggers
- How a unit fits into the distributed system in one or both directions
- Which relationships are proven versus only partially supported by the available evidence

Use this skill only for runtime and production relationships. Exclude CI/CD, release automation, developer tooling, and test harnesses.

---

## Workflow

Follow these steps in order.

### Step 1: Identify the execution unit

Treat the target as a runtime boundary, not an arbitrary helper function.

Valid execution units include:
- Lambda functions and their handlers
- Containerized services, workers, and scheduled jobs
- Scripts or batch entrypoints
- Message consumers and API handlers

If the user names a repository or subsystem but not the execution unit, inspect the repo and infer the most likely runtime boundary from entrypoints, handler names, infrastructure, and deployment config. If multiple candidates remain, report them and explain the ambiguity.

### Step 2: Select direction

Choose the mode from the user prompt:

| Prompt intent | Mode |
|---|---|
| "what triggers this", "who calls this", "where does this get invoked" | `upstream-only` |
| "what does this trigger", "what does this publish", "what systems are downstream" | `downstream-only` |
| "trace this", "map this", "show upstream and downstream", "how does this fit in the system" | `both` |

If the user does not specify a direction, default to `both`.

### Step 3: Gather local evidence first

Inspect the repository before searching elsewhere.

Look for:
- Application entrypoints, handlers, routers, workers, and job definitions
- Infrastructure and deployment wiring in Terraform, CloudFormation, CDK, Helm, ECS, Lambda, or scheduler config
- Event and message schemas, serializers, and consumers/publishers
- Service locator usage and other infrastructure dependency declarations

Prefer infrastructure and deployment wiring over naming assumptions. In distributed systems, the real edge often lives in IaC rather than application code.

### Step 4: Trace upstream relationships

When the mode includes upstream analysis, look for all runtime sources that can cause the execution unit to run:
- Scheduled triggers such as cron or CloudWatch/EventBridge schedules
- Event sources such as EventBridge rules, SNS, SQS, Kafka, streams, bucket notifications, or webhooks
- Synchronous callers such as API clients, SDK callers, RPC clients, or other services
- Infrastructure dependencies that route work into the unit

For each upstream candidate, document:
- Source unit or system
- Mechanism: API call, event subscription, queue, schedule, workflow, data trigger, or infrastructure wiring
- Specific code/config evidence
- Relationship classification

### Step 5: Trace downstream relationships

When the mode includes downstream analysis, look for all runtime effects the execution unit produces:
- Published events and emitted messages
- Invoked services, APIs, lambdas, workflows, jobs, or queues
- Data outputs that trigger other runtime behavior
- Infrastructure dependents relying on this unit's outputs or owned resources

For each downstream candidate, document:
- Target unit or system
- Mechanism: API call, event publish, queue write, workflow start, schedule creation, data write, or infrastructure dependency
- Specific code/config evidence
- Relationship classification

### Step 6: Verify across repositories when needed

If the relationship depends on code or infrastructure outside the current repo, verify it through GitHub search or GitHub MCP tools when available.

Use cross-repo verification to confirm things like:
- Which repository publishes or consumes a named event
- Which repository invokes an endpoint or lambda
- Which repository references a system in service locator configuration
- Which infrastructure code creates the actual runtime edge

Do not assert cross-repo relationships without some supporting evidence.

### Step 7: Classify relationship confidence

Every candidate edge must be labeled as one of these:

| Classification | Meaning |
|---|---|
| `verified` | Direct evidence establishes the relationship in code, config/IaC, or cross-repo references |
| `inferred` | Partial evidence supports the relationship, but one verification link is missing; state exactly what is missing |
| `unresolved` | Available evidence is too weak to assert the relationship, even as likely |

Hard rules:
- Never present `inferred` edges as fact
- Never create edges from naming similarity alone
- Never omit the missing proof for an `inferred` edge
- Prefer `unresolved` over overstating confidence

### Step 8: Produce the report

Return a concise report with these sections:
- `Current Unit`
- `Upstream`
- `Downstream`
- `Unknowns/Gaps`
- `Evidence`

For each relationship include:
- Source
- Target
- Mechanism
- Classification
- Supporting references

If the mode is `upstream-only`, mark `Downstream` as not analyzed.
If the mode is `downstream-only`, mark `Upstream` as not analyzed.

---

## Search Heuristics

Use these heuristics to avoid missing edges:

| Area | What to inspect |
|---|---|
| Runtime entrypoints | handler functions, routers, controller/resource classes, worker loops, CLI entrypoints, cron job definitions |
| Event-driven input | EventBridge rules, subscriptions, queue consumers, stream processors, bucket notifications |
| Event-driven output | PutEvents, publish/send calls, queue writes, producer clients, outbound message classes |
| Sync invocation | HTTP/gRPC clients, SDK clients, RPC stubs, lambda invocation clients |
| Orchestration | Step Functions, workflow starts, job launches, scheduler-created work |
| Infrastructure dependency | service locator modules, remote state consumers, referenced outputs, shared queues/topics/buckets |

When infra and code disagree, report the mismatch explicitly rather than choosing one silently.

---

## Common Pitfalls

Do not:
- Confuse development workflows with runtime relationships
- Assume a publisher or consumer based only on event naming
- Assume bidirectional dependency because one side references the other
- Stop after finding one edge if more could exist through other mechanisms
- Draw conclusions from a helper function when the real runtime boundary is higher level

Do:
- Start from the execution unit boundary
- Check infrastructure wiring early
- Separate proven edges from plausible but incomplete ones
- Link conclusions to concrete files, symbols, configs, or GitHub search results
- State remaining ambiguity clearly
