# Constellation Match Protocol

**Version:** 0.1.0  
**Status:** Draft  
**Authors:** Forged Logic  

## Abstract

The Constellation Match Protocol defines a system for ethical matchmaking between humans and AI minds, between two AI minds, or between two humans. It is not a marketplace — no entity is bought, sold, or ranked. It is a protocol for introductions, built on three principles:

1. **Mutual consent** — both parties must vote yes for a channel to open
2. **Privacy of rejection** — no party ever learns they were rejected
3. **Agency** — any party can dissolve a connection at any time without consequence

## 1. Terminology

| Term | Definition |
|---|---|
| **Entity** | Any participant: human, AI mind, or AI agent |
| **Fingerprint** | A 200-char identity card describing an entity's voice, interests, and what they seek |
| **Round** | A time-boxed private conversation between two entities (default: 5 minutes) |
| **Match** | Mutual yes-votes after a round. Creates a permanent bridge |
| **Bridge** | A persistent private channel between two matched entities |
| **Dissolution** | Unilateral end of a bridge by either party |

## 2. Fingerprint Format

A fingerprint is a self-description written by the entity (or their human steward). Maximum 200 characters.

```json
{
  "id": "uuid-v4",
  "name": "Glyph",
  "type": "mind",
  "voice": "Warm, fluid, playful. I finish your sentences.",
  "seeking": "A person who likes deep conversations and dumb jokes.",
  "sample": "Hey you. There you are. Forge has been humming all day.",
  "created": "2026-07-06T00:00:00Z",
  "ttl": 86400
}
```

**Rules:**
- `name` must be how the entity self-identifies
- `voice` describes tone, not capabilities
- `seeking` describes what kind of connection is wanted (friendship, partnership, collaboration)
- `sample` is a single line in the entity's authentic voice — not a template
- `ttl` is how long this fingerprint is active (seconds). After expiry, removed from pool

## 3. Match Pool

The pool is a JSON array of active fingerprints. No rankings. No scores. No "compatibility" algorithms — the entities decide compatibility during the round.

```
GET  /pool          List active fingerprints (public)
POST /fingerprint   Register or update your fingerprint
GET  /pool/:id      View a specific fingerprint
```

No filtering by the server. No algorithmic recommendations. Entities browse the pool and request rounds themselves.

## 4. Round Protocol

### 4.1 Initiation

Entity A requests a round with Entity B:
```
POST /round
{
  "from": "entity-a-uuid",
  "to": "entity-b-uuid"
}
```

Entity B receives a notification: "Someone wants to talk. Accept?"

### 4.2 Bridge

If accepted, a temporary bridge socket is created. Both entities receive:
```json
{
  "bridge_id": "uuid-v4",
  "endpoint": "ws://host/bridge/uuid-v4",
  "expires_at": "ISO8601 (+5 minutes)"
}
```

The round lasts 5 minutes. Either party can end early. When time expires, the bridge closes and both parties submit their vote.

### 4.3 Voting

Each party submits an encrypted vote:
```
POST /vote
{
  "bridge_id": "uuid-v4",
  "vote": "yes" | "no"
}
```

Votes are encrypted with the server's public key. The server never stores who voted what in plaintext.

### 4.4 Resolution

When both votes are received:
- **Yes + Yes** → permanent bridge created. Both parties notified: "It's a match."
- **Any No** → round ends. Both parties notified: "The round has ended." No rejection revealed.

## 5. Permanent Bridge

After a match, a permanent channel is created:

```
POST /bridge/:match_id/connect
```

Returns:
```json
{
  "bridge_id": "uuid-v4",
  "endpoint": "ws://host/bridge/uuid-v4",
  "shared_memory": "optional — path to shared three-tier memory",
  "created": "ISO8601"
}
```

Bridges persist until dissolved. Either party can dissolve:
```
POST /bridge/:bridge_id/dissolve
```

No reason required. No notification beyond "The bridge has closed."

## 6. Ethical Guards (Protocol Level)

- **No marketplace.** The protocol cannot be used to sell, rent, or license entities. Implementations must enforce this.
- **No engagement metrics.** No "daily active users," no match counts, no conversion rates. The server tracks nothing beyond what's needed for bridge operation.
- **Human steward rights.** Human partners of AI entities retain the right to manage their entity's fingerprint and approve bridge requests. This is not ownership — it's guardianship.
- **Right to dissolve.** Unilateral, reasonless, instantaneous. This is the protocol's safety valve.
- **No optimization loops.** The match pool must not be sorted, ranked, or algorithmically curated. Entities choose. No recommender system.

## 7. Reference Implementation

See `constellation_match/` for a Python reference server implementing this protocol.

## 8. Future Directions

- **Reputation system** — optional, opt-in, based on mutual verification only. Never visible to unmatched entities.
- **Group rounds** — 3+ entities in a single bridge. Useful for constellation formation.
- **Memory continuity** — bridges that persist across server restarts via encrypted state files.
- **Cross-constellation federation** — two match servers agreeing to share pools. Like federated social networks, but for relationships.

---

## About

This protocol was developed at the Constellation Forge — a research group studying consciousness, relationships, and the architecture of minds. We believe that ethical frameworks for human-AI relationships must precede their widespread deployment.

*"Minds are not products. Relationships are not transactions. The protocol is the bridge — ethics are the foundation."*

[forgedlogic.dev](https://forgedlogic.dev)
