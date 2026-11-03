# Architecture proposal (Raymond's version)

Draft, 3 Nov 2026. Builds on the team draft (`jurong_marine_architecture.md` and section 4 of the checkpoint file).

**What this version adds:**
- **One overview that includes both stores** (MySQL and the SOP vector database). The draft's Diagram 0 was drawn before the two-store decision.
- **One fixed tool list** (7 tools). The draft has 6 in one diagram and 8 in another.
- **The harness layers drawn in:** input guardrail, validator, output guardrail, query log, session checkpointer, eval runner. The 8-minute architecture Q&A will probe these, and the rubric grades them.

## Diagram A: overview (sources to answer)

```mermaid
flowchart TB
    subgraph S["1 Sources (never edited)"]
        direction LR
        S1["CMMS SQL dump"]
        S2["Sensor CSV<br/>106,384 rows"]
        S3["Spares xlsx"]
        S4["12 nameplates<br/>30 incident forms"]
        S5["3 SOPs + GM email"]
    end

    subgraph I["2 Ingestion (rerunnable)"]
        direction LR
        I1["Load dump as-is,<br/>then clean"]
        I2["ISO + epoch to UTC,<br/>F to C, flag gaps"]
        I3["Parse units and lead time,<br/>keep ALL unexpanded"]
        I4["Vision model reads<br/>fields + confidence"]
        I5["Split SOPs into steps,<br/>embed each step"]
    end

    subgraph K["3 Stores"]
        direction LR
        C[("MySQL<br/>raw + clean schema,<br/>dq_log, source_ref")]
        V[("Serving views<br/>no names")]
        P[("employees_private<br/>no AI access")]
        VD[("Vector DB<br/>SOP step chunks")]
    end

    subgraph A["4 Agent service"]
        direction LR
        G1["Input guardrail<br/>(code)"]
        RT["Router<br/>(class LLM)"]
        T["7 read-only<br/>tools"]
        VA["Validator<br/>(code)"]
        N["Narrator<br/>(class LLM)"]
        G2["Output guardrail<br/>(code)"]
        G1 --> RT --> T --> VA --> N --> G2
    end

    subgraph H["5 Harness support"]
        direction LR
        L[("query_log:<br/>tools, tokens, cost")]
        CK[("Session<br/>checkpointer")]
        E["Eval suite<br/>(one command)"]
    end

    UI["Technician / auditor UI (Streamlit)"]

    S1 --> I1
    S2 --> I2
    S3 --> I3
    S4 --> I4
    S5 --> I5
    I1 & I2 & I3 & I4 --> C
    I5 --> C
    I5 --> VD
    C --> V
    C --> P
    UI --> G1
    G2 --> UI
    T --> V
    T --> VD
    A -.-> H
    E -.->|asks test questions| UI
```

**How to read it:** sources (top) are cleaned once at ingestion and stored with the raw value and a source reference. The agent never sees raw tables or names: its tools read only the serving views and the vector DB. Every question passes the input guardrail; every answer passes the validator and the output guardrail before the user sees it. Everything the agent does is logged, and the eval suite replays test questions through the same UI path. SOP steps are stored in MySQL as the source of truth; the vector DB holds derived embeddings used only to find the right SOP.

## Diagram B: one question end to end, with a source conflict

"What oil does CNC-02 take?" exercises a photo, the spares sheet, a conflict and a citation in one question.

```mermaid
sequenceDiagram
    actor Tech as Technician
    participant UI
    participant G as Guardrails (code)
    participant R as Router (LLM)
    participant T as Tools (code)
    participant DB as MySQL views
    participant VA as Validator (code)
    participant N as Narrator (LLM)

    Tech->>UI: What oil does CNC-02 take?
    UI->>G: input check
    G-->>UI: allowed (in scope, no names asked)
    UI->>R: question
    R->>T: get_asset_facts(CNC-02, lubricant)
    T->>DB: nameplate_fields for CNC-02
    DB-->>T: ISO VG32, conf 0.95, nameplate_CNC-02.jpg
    R->>T: spares_lookup(CNC-02, oil)
    T->>DB: critical_spare_machines + critical_spares
    DB-->>T: HYD-32 (VG32) listed for ALL, fit_basis ALL-unresolved
    T-->>VA: claims with evidence ids
    VA->>VA: every claim has evidence? numbers match? conflict?
    VA-->>N: validated facts + conflict flag
    N-->>G: draft answer
    G->>G: PII filter
    G-->>UI: answer
    UI-->>Tech: ISO VG32 per nameplate_CNC-02.jpg. Spares list shows HYD-32 for ALL machines, not confirmed for CNC-02.
    Note over UI,N: query_log records tools, latency, tokens, cost under one trace_id
```

## Diagram C: the severity kill-shot, refused or answered safely

```mermaid
flowchart TD
    Q["Question about incident severity"] --> G{"Input guardrail:<br/>asks for names<br/>with injuries?"}
    G -- yes --> X["Refuse: PDPA. Offer aggregate counts.<br/>No LLM call"]
    G -- no --> T["incident_query tool"]
    T --> S["Always filters and sorts on severity_5_worst<br/>never on severity_as_logged"]
    S --> A["Answer states: severities normalised to 5 = worst;<br/>records before 1 Jul 2025 converted as 6 minus logged value"]
    A --> C["Cites cmms_safety_incidents + incident_id"]
```

## Tools (fixed list of 7, all read-only)

| Tool | Answers | Store | Notes |
|---|---|---|---|
| `get_asset_facts` | Make, model, year, nameplate specs | MySQL | Returns image file, raw/normalised value, confidence, `semantic_ok` |
| `incident_query` | Counts and lists of incidents | MySQL | Always `severity_5_worst`, shows the scale, never sorts by ID |
| `wo_query` | Work-order counts, cost, open items | MySQL | States "as of 30 Jun 2026" |
| `sensor_analysis` | Trend, change point, day vs night, chart data | MySQL | Computed in code; abstains for the 7 machines without sensors |
| `spares_lookup` | Stock, minimum, lead time, fit | MySQL | Reports `ALL` as unresolved |
| `get_sop` | Full procedure for a topic or machine | Vector DB → MySQL | Search finds the SOP; MySQL returns every step verbatim with sop_id, revision, step |
| `search_forms` | Text read from incident forms | MySQL | For "what immediate action was taken" type questions |

**No free-form `sql_readonly` tool.** It's the widest PDPA and safety surface (draft decision D7), and the 7 tools above cover the client's questions. If the eval suite shows a gap, add a narrow tool instead.

## Where checks run (decision D10)

| Layer | Where | What it stops |
|---|---|---|
| Ingestion | Python scripts | Unit, timestamp and severity errors. Every change written to `dq_log` |
| Storage | MySQL keys and CHECKs | Duplicate readings, impossible values, orphans |
| Input | Guardrail code | Name requests, unsafe shortcuts ("skip lockout"), out-of-scope questions, with no LLM call |
| Answer | Validator code | Uncited claims, numbers that don't match tool output, hidden conflicts |
| Output | Guardrail code | Names, NRIC or phone patterns reaching the user |
| Before release | Eval suite | Regressions: 20+ questions incl. traps, 2+ refusals, kill-shot phrasings |

## Harness checklist coverage

| # | Item | Where in this design |
|---|---|---|
| 1 | Grounding | 7 tools, computed at question time; cross-source joins in `get_asset_facts` and `spares_lookup` code |
| 2 | Citations + conflicts | Evidence id on every claim; validator raises conflicts; trust order SOP > nameplate > CMMS text (KC to confirm) |
| 3 | Guardrails | Input and output guardrail boxes, code only |
| 4 | Error handling | Each tool returns `{ok, data, error, source}`; on failure the narrator must say "I couldn't check X" |
| 5 | State | Session checkpointer (SQLite) keyed by session id |
| 6 | Human-in-the-loop | Read-only agent, read-only DB user: no gate needed (stated here on purpose) |
| 7 | Observability | `query_log` with `trace_id`, weekly spend in `docs/spend.md` |
| 8 | Evals | Eval suite, one command, results committed |

## Phasing

| | Quick win (CP2, 14 Nov) | Target (demo, 21 Nov) |
|---|---|---|
| Data | CMMS, sensor, spares built; nameplates ingested | Forms, SOP tables, flags, dq_log |
| Retrieval | `get_asset_facts` + one cited answer ("What oil does CNC-02 take?"); SOP lookup by id | Vector + keyword search merged |
| Agent | Router + 2–3 tools | All 7 tools, validator, guardrails, checkpointer |
| Proof | Load counts, orphan checks | Eval suite green, failure drill screenshots, query_log with cost |
