# ADC Development Constitution

## Core Principles

### I. Traceable business requirements（需求可追踪性）

Identify the actor, expected outcome, invariant and failure response before implementation. Tie each changed requirement to an observable acceptance case.

### II. Module ownership（信息隐藏）

Reuse the existing Django and PostgreSQL module boundaries. Clinical owns reports and decisions, scheduling owns appointments and resource locks, and finance owns amounts and cash facts. Patient clients consume shared authorized projections.

### III. Patient privacy and durable history（权限与历史）

The server verifies the current actor, subject, role and scope before sensitive reads or writes. Preserve independent authorization, transactions and audit. Keep synthetic records isolated and credentials in private guides. Use additive migrations when persistent facts change.

### IV. Evidence for the exact version（版本可核对）

Use focused regression and database facts to verify functionality. Run the established CI for the exact integrated candidate before promoting it. Record browser, developer tool, phone and provider acceptance from the environment that ran them.

### V. Small, reviewable changes（最小实现）

Codex owns server, web, contracts and integration. WorkBuddy owns the native client and developer-tool evidence. Give each party runnable samples and a reproducible handoff. Keep the business change focused and use established code paths.

## Governance

Follow `AGENTS.md` for current application rules. Update the relevant feature contract and evidence when changing an interface.

**Version** 1.0.0 · **Adopted** 2026-11-15
