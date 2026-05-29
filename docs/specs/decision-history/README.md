# Feature: Decision History for Portfolio Manager Continuity

## Requirements

**FR-1**: After each pipeline run, the system MUST save the `portfolio_manager`'s decision to a persistent history file, regardless of the `ALPHACOUNCIL_PERSIST_ENABLED` setting.

**FR-2**: Before each pipeline run, the system MUST read the most recent decision for the same ticker from the history file and inject it into `portfolio_manager`'s instruction as reference context.

**FR-3**: If no previous decision exists for the ticker (first run), the system MUST gracefully skip the injection without affecting the pipeline.

**FR-4**: The `portfolio_manager` agent MUST have `output_key="portfolio_decision"` so its output is captured in session state for persistence.

**FR-5**: The decision history file MUST use JSON Lines format (`.jsonl`), one record per line, append-only.

**FR-6**: When `GCS_BUCKET_ROOT` environment variable is configured, the system MUST also save the decision history to GCS at `{gcs_root}/{market}/{ticker}/decision_history.jsonl`. When not configured, save locally to `reports/{market}/{ticker}/decision_history.jsonl`.

## Acceptance Criteria

- **AC-1**: GIVEN a first run for ticker AAPL WHEN the pipeline completes THEN a new entry is appended to `reports/us/AAPL/decision_history.jsonl`
- **AC-2**: GIVEN an existing `decision_history.jsonl` for AAPL WHEN a second run starts THEN the `portfolio_manager` instruction includes the previous decision text
- **AC-3**: GIVEN a first run for ticker MSFT (no history) WHEN the pipeline runs THEN the `portfolio_manager` instruction does NOT reference any previous decision, and no error occurs
- **AC-4**: GIVEN `ALPHACOUNCIL_PERSIST_ENABLED=false` WHEN the pipeline completes THEN the decision history IS still saved (unlike `portfolio_report`)
- **AC-5**: GIVEN the pipeline runs for AAPL and then for MSFT WHEN AAPL runs again THEN only AAPL's last decision is loaded (not MSFT's)
- **AC-6**: GIVEN `GCS_BUCKET_ROOT=gs://my-bucket/prefix` WHEN the pipeline completes THEN a decision history entry appears at `gs://my-bucket/prefix/us/AAPL/decision_history.jsonl`

## Data Model

### Decision History Record (JSON Lines)

Stored in: `reports/{market}/{ticker}/decision_history.jsonl`

```json
{
  "ticker": "AAPL",
  "market": "us",
  "date": "2026-05-29",
  "session_id": "abc123def456",
  "full_text": "[portfolio_manager 的完整輸出文字]"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | string | Stock ticker symbol (e.g. "AAPL", "2330") |
| `market` | string | Market code: "us" or "tw" |
| `date` | string | ISO date of the run |
| `session_id` | string | Unique session identifier |
| `full_text` | string | Complete output text from portfolio_manager |

The file is append-only; the last complete line is the most recent decision.

### State Contract

| State Key | Type | Set By | Read By | Description |
|-----------|------|--------|---------|-------------|
| `portfolio_decision` | string | portfolio_manager (via output_key) | CLI (after run, to persist) | Raw output text |
| `previous_decision` | string | CLI (initial_state) | portfolio_manager (instruction) | Formatted previous decision context block |

## API Contract

No new API endpoints. This is a CLI-level + agent-level change.

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `alpha_council/utils/decision_history.py` | `save_decision()`, `load_previous_decision()`, `format_previous_decision_for_prompt()` |

### Modified Files

| File | Change |
|------|--------|
| `alpha_council/agent.py` | Add `output_key="portfolio_decision"` to `portfolio_manager`; inject `previous_decision` in instruction |
| `alpha_council/cli/run.py` | Before run: load history → `initial_state["previous_decision"]`; After run: save `state["portfolio_decision"]` |

## Out of Scope

- Cross-ticker portfolio-level decision history aggregation
- Decision editing or deletion
- Structured parsing of LLM output into structured fields (saves raw text only)
- telegram-bot / fast_api_app integration (can be added later)
