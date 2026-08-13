# Client Brief — Jurong Marine & Engineering Pte Ltd

*From: KC Tan, General Manager (your client contact)*

We're a 32-man ship-repair and precision engineering shop in Tuas. MOM WSH audit expected Q4.
Two asks, one deadline.

**Ask 1 — Safety & maintenance knowledge agent:** techs ask "what oil does CNC-02 take", "what's
the grease interval for the compressor", "what's the SOP before entering the blasting chamber".
Answers live on the machine nameplates (photographed), in the SOP documents, and in the CMMS.
The agent must answer with the source shown — auditors don't accept vibes.

**Ask 2 — Audit-ready incident & condition reporting:** incident history queryable WITHOUT mixing
up the severity scales (we flipped from 1=worst to 5=worst in Jul 2025 and never converted old
records — the auditor WILL test this). And the night shift says CNC-02 feels "off": analyse the
vibration/temperature logs and tell me if they're right, in a chart I can show the auditor.

**Known landmines:**
- Sensor CSV: mixed ISO and epoch-millisecond timestamps, temperatures in both °C and °F, gaps.
- Spares list mixes metric and imperial (bearings in mm, belts and seals in inches).
- Nameplate photos are genuinely bad photos. So are real ones.

**Data manifest:** `sql/jurongmarine_cmms.sql`, `logs/vibration_temp_2026H1.csv` (~106k rows),
`tabular/critical_spares.xlsx`, `images/` (12 nameplates, 30 incident reports), `docs/sops/`.

---

## Engagement rules (same for all teams)

You are a squad of five **forward deployed engineers**. The client is non-technical.
The instructor will role-play your client contact at the demo.

**You must deliver, on presentation day (Sat 21 Nov 2026, 5 min pitch + live demo per team):**

1. A working AI application using the LLM API endpoint provided in class (open API, key issued per team). No other paid AI services.
2. Ingestion of ALL data source types in this package (SQL, tabular, images, documents). The app must answer from *this* data, not model memory.
3. An architecture diagram and at least two Mermaid diagrams (e.g. data flow, sequence diagram of one query, ER diagram of your cleaned schema).
4. A one-page data quality report: what was wrong with the client's data and what you did about it.
5. A live demo in which the client will ask unscripted questions.

**Constraints:**
- The raw data is too large to paste into a prompt. You are expected to build retrieval / pipelines, not a mega-prompt.
- Answers must cite their source (table, file, or image) so the client can verify.
- If the data cannot answer a question, the app must say so instead of guessing.
- Handle the data-protection issues you find. You may be asked about PDPA on demo day.

**Marking signal (what the client cares about):** correct answers on messy cross-source questions,
graceful handling of contradictions and missing data, clear architecture, and a demo that survives
questions you did not rehearse.
