---
status: backlog
priority: P2
agent_claimed: null
claimed_at: null
updated: 2026-08-19
---

# Animal Shelter API Integration

> **Repo:** k9-overwatch
> **Description:** Integrate IndyHumane, IACS, and county shelter APIs for live pet listings

---

## Context

Core data pipeline — pull adoptable/lost/found animals from IndyHumane (PetPoint), IACS (24PetWatch), and surrounding county shelters. Normalize fields into unified schema.

---

## Acceptance Criteria

- [ ] PetPoint REST API connected with credential management
- [ ] 24PetWatch ShelterStream integration for IACS data
- [ ] Unified animal schema with source tracking and dedup hash
- [ ] Scheduled sync with error alerting and retry logic

---

## Technical Notes

- FastAPI background tasks for sync; use Pydantic models for schema normalization; store raw + normalized in Postgres
