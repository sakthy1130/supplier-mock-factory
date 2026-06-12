# Design Notes — Conversation Summary

Captured from SMF design sessions (2026-06). Use with ARCHITECTURE.md for context.

## Original problem

Manual process to create supplier mocks for 7 API types, edit scenarios (package count, room names, CP, refundable), sync bookingIds across book/getOrder/cancel, create contracts with mock URLs, attach to apiKey, run hotel booking.

## Rejected approaches

| Approach | Why rejected |
|----------|--------------|
| MongoDB knowledge store | Unnecessary ops; git JSON templates sufficient |
| Runtime LLM to "understand" responses | Non-deterministic; use offline field maps |
| Staging callback host | User cannot provide; MockServer-only BookingIdInjector instead |
| Java new project | User chose Python for Cursor speed + separate product |
| Hybrid Java JAR + Python | Two runtimes; hard for Cursor-only maintenance |

## Chosen approach

- **New repo**: `supplier-mock-factory`
- **Python FastAPI** backend ports Java logic from qaBackend_Enigma
- **React + shadcn** frontend for manual QA
- **Template library** from reference SIDs (user has SIDs)
- **BookingIdInjector**: new ids per `createScenario()`, `refresh_booking_ids()` for repeat bookings
- **New apiKey per scenario**
- **Namespace** isolation on shared staging MockServer

## Timeline expectation (Cursor-driven)

- Coding: hours per phase with Cursor
- Calendar: **7–14 days** including staging integration debug
- MVP without UI: **3–5 days** (CLI orchestrator)

## Scope v1

- Users: manual QA
- Env: shared staging MockServer
- Suppliers: HBS + EXP
- Log types: all 7
