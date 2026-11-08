"""LLM clients (ADR-005, ADR-006; R-14, R-15, R-30, R-36). OWNER: agents agent.

The model has NO tools and NO actions: it only returns JSON validated against a schema.
Untrusted text goes in as delimited data (R-14, ADR-007). Every call yields an LlmCallRecord that
the workflow writes to the audit log (R-21).

Backends:
- OfflineLlmClient: deterministic, no network, the default (Settings.llm_backend="offline").
  It implements the same prompt templates with transparent heuristics (disputes.agents.offline)
  so the whole pipeline runs in CI and demos. It must NOT import synthgen or read labels
  (test-enforced). Its quality is NOT the product's model quality.
- AnthropicLlmClient: Messages API, pinned model ID (R-30: mismatch -> LlmUnavailable, no
  fallback, no retry). Off until ZDR is confirmed (ADR-006).
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable, Protocol

import jsonschema

from disputes.domain import LlmCallRecord

log = logging.getLogger("disputes.agents.llm")

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
OFFLINE_MODEL_ID = "offline-heuristic-0.1"

# R-36 price table (USD per million tokens). Config, not code paths: pass `prices=` to override.
# The Anthropic figures are PLACEHOLDERS (verified=False): confirm on the provider's pricing page
# for the pinned model before any cost report is quoted.
PRICES: dict[str, dict] = {
    OFFLINE_MODEL_ID: {"input_per_mtok": 0.0, "output_per_mtok": 0.0, "verified": True,
                       "source": "offline backend makes no paid call"},
    "claude-sonnet-5-5": {"input_per_mtok": 3.0, "output_per_mtok": 15.0, "verified": False,
                          "source": "PLACEHOLDER - not checked against the provider price list"},
}


class LlmUnavailable(RuntimeError):
    """Timeout, error after retry, budget exhausted, or model-ID mismatch -> LLM_UNAVAILABLE."""


class ModelMismatch(LlmUnavailable):
    """R-30: provider returned a different model ID. Never retried, never silently accepted."""


class LlmCallError(RuntimeError):
    """One failed attempt (bad JSON, schema violation, SDK error). Retryable once by CaseBudget."""

    def __init__(self, message: str, record: LlmCallRecord | None = None):
        super().__init__(message)
        self.record = record


class LlmClient(Protocol):
    model_id: str

    def complete_json(self, prompt_template_id: str, data: dict, schema: dict) -> tuple[dict, LlmCallRecord]:
        """Render template `prompt_template_id` (src/prompts/<id>.md) with `data`, call the model,
        validate against `schema`, return (output, record). Raises LlmUnavailable."""
        ...


# ----------------------------------------------------------------------------- prompts
def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@lru_cache(maxsize=None)
def load_template(template_id: str) -> tuple[str, str, str]:
    """(system, user, sha256). The hash covers the expanded template (template file with the shared
    rules file substituted), i.e. exactly the fixed text the model sees apart from the data."""
    if not re.fullmatch(r"[a-z_]+", template_id):
        raise ValueError(f"bad template id {template_id!r}")
    raw = (PROMPT_DIR / f"{template_id}.md").read_text(encoding="utf-8")
    rules = (PROMPT_DIR / "_rules.md").read_text(encoding="utf-8")
    rules = re.sub(r"<!--.*?-->\s*", "", rules, flags=re.S).strip()
    expanded = raw.replace("{{RULES}}", rules)
    body = re.sub(r"<!--.*?-->\s*", "", expanded, flags=re.S)
    m = re.search(r"^## system\s*\n(.*?)^## user\s*\n(.*)\Z", body, flags=re.S | re.M)
    if not m:
        raise ValueError(f"template {template_id} lacks '## system' / '## user' sections")
    return m.group(1).strip(), m.group(2).strip(), sha256_text(expanded)


def delimit(name: str, value) -> str:
    """One untrusted data block (ADR-007). The JSON payload has '<' and '>' escaped as \\u003c /
    \\u003e (still valid JSON), so no payload can open or close a tag; the nonce is derived from the
    payload, so the closing tag cannot be predicted from inside it."""
    payload = _canonical(value).replace("<", "\\u003c").replace(">", "\\u003e")
    nonce = sha256_text(name + "\x00" + payload)[:16]
    return (f'<untrusted_data name="{name}" nonce="{nonce}">\n{payload}\n'
            f'</untrusted_data nonce="{nonce}">')


def render_prompt(template_id: str, data: dict) -> tuple[str, str, str]:
    """(system, user, template_sha256). Every top-level data key becomes its own delimited block."""
    system, user, h = load_template(template_id)
    blocks = "\n".join(delimit(k, data[k]) for k in sorted(data))
    return system, user.replace("{{DATA}}", blocks), h


def input_hashes(data: dict) -> tuple[str, ...]:
    """sha256 of each top-level input, in key order (R-21 'input hashes')."""
    return tuple(sha256_text(_canonical({k: data[k]})) for k in sorted(data))


def _est_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def _cost(model_id: str, tin: int, tout: int, prices: dict) -> float:
    p = prices.get(model_id)
    if p is None:
        log.warning("no price entry for model %s; cost recorded as 0.0", model_id)
        return 0.0
    return round(tin * p["input_per_mtok"] / 1e6 + tout * p["output_per_mtok"] / 1e6, 8)


def validate_output(output, schema: dict) -> None:
    try:
        jsonschema.validate(output, schema)
    except jsonschema.ValidationError as e:
        raise LlmCallError(f"schema violation: {e.message[:200]}") from None


# ----------------------------------------------------------------------------- offline
class OfflineLlmClient:
    """Deterministic heuristic backend. No network. Model ID 'offline-heuristic-0.1', cost 0.

    Implements each template with transparent rules over the same data the real model would
    receive (see disputes.agents.offline). It exists so the pipeline runs end to end in CI and
    demos; its agreement numbers are not the product's model quality."""

    model_id = OFFLINE_MODEL_ID

    def __init__(self, prices: dict | None = None):
        self.prices = prices or PRICES

    def complete_json(self, prompt_template_id: str, data: dict, schema: dict) -> tuple[dict, LlmCallRecord]:
        from disputes.agents import offline
        t0 = time.monotonic()
        system, user, h = render_prompt(prompt_template_id, data)
        handler = offline.HANDLERS.get(prompt_template_id)
        if handler is None:
            raise LlmCallError(f"offline backend has no handler for {prompt_template_id}")
        out = handler(data)
        validate_output(out, schema)
        tin, tout = _est_tokens(system + user), _est_tokens(_canonical(out))
        rec = LlmCallRecord(
            model_id=self.model_id, prompt_template_id=prompt_template_id, prompt_sha256=h,
            input_sha256s=input_hashes(data), output=out, error=None,
            latency_ms=int((time.monotonic() - t0) * 1000), tokens_in=tin, tokens_out=tout,
            cost_usd=_cost(self.model_id, tin, tout, self.prices), attempt=1)
        return out, rec


# ----------------------------------------------------------------------------- anthropic
class AnthropicLlmClient:
    """Anthropic Messages API with a pinned model ID (R-30) and schema-constrained JSON output.

    No tools are ever passed. The returned model ID is logged next to the requested one; any
    mismatch raises ModelMismatch (an LlmUnavailable) with no fallback. SDK retries are disabled:
    retry policy belongs to CaseBudget (R-15). Tests use a mocked SDK client only (no network).
    """

    def __init__(self, cfg, *, sdk_client=None, prices: dict | None = None, max_tokens: int = 2048):
        self.model_id = cfg.llm_model_id
        self.prices = prices or PRICES
        self.max_tokens = max_tokens
        self.timeout_s = cfg.llm_call_timeout_s
        if sdk_client is None:  # pragma: no cover - real network client, never built in tests
            import anthropic
            sdk_client = anthropic.Anthropic(timeout=cfg.llm_call_timeout_s, max_retries=0)
        self._sdk = sdk_client

    def complete_json(self, prompt_template_id: str, data: dict, schema: dict) -> tuple[dict, LlmCallRecord]:
        system, user, h = render_prompt(prompt_template_id, data)
        t0 = time.monotonic()
        base = dict(model_id=self.model_id, prompt_template_id=prompt_template_id, prompt_sha256=h,
                    input_sha256s=input_hashes(data), attempt=1)
        try:
            resp = self._sdk.messages.create(
                model=self.model_id,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
                timeout=self.timeout_s,
            )
        except Exception as e:  # SDK / transport error: one failed attempt
            rec = LlmCallRecord(**base, output=None, error=f"{type(e).__name__}: {str(e)[:200]}",
                                latency_ms=int((time.monotonic() - t0) * 1000), tokens_in=0,
                                tokens_out=0, cost_usd=0.0)
            raise LlmCallError(rec.error, rec) from None
        latency = int((time.monotonic() - t0) * 1000)
        returned = getattr(resp, "model", None)
        usage = getattr(resp, "usage", None)
        tin = int(getattr(usage, "input_tokens", 0) or 0)
        tout = int(getattr(usage, "output_tokens", 0) or 0)
        cost = _cost(self.model_id, tin, tout, self.prices)
        log.info("llm call template=%s requested_model=%s returned_model=%s", prompt_template_id,
                 self.model_id, returned)
        if returned != self.model_id:
            rec = LlmCallRecord(**base, output=None,
                                error=f"MODEL_MISMATCH requested={self.model_id} returned={returned}",
                                latency_ms=latency, tokens_in=tin, tokens_out=tout, cost_usd=cost)
            err = ModelMismatch(rec.error)
            err.record = rec
            raise err
        text = "".join(getattr(b, "text", "") for b in (resp.content or []) if getattr(b, "type", "") == "text")
        try:
            out = json.loads(text)
            validate_output(out, schema)
        except (json.JSONDecodeError, LlmCallError) as e:
            rec = LlmCallRecord(**base, output=None, error=f"BAD_OUTPUT: {str(e)[:200]}",
                                latency_ms=latency, tokens_in=tin, tokens_out=tout, cost_usd=cost)
            raise LlmCallError(rec.error, rec) from None
        return out, LlmCallRecord(**base, output=out, error=None, latency_ms=latency,
                                  tokens_in=tin, tokens_out=tout, cost_usd=cost)


# ----------------------------------------------------------------------------- budget
class CaseBudget:
    """R-15: ≤ cfg.llm_max_calls_per_case calls and ≤ cfg.llm_case_budget_s seconds per case;
    1 retry with backoff per call. Collects LlmCallRecords for the audit log and cost (R-36).

    Counting: a "call" is one logical step request (classify, extract_claims, map_claims, draft,
    draft retry). Each call may make up to 1 + cfg.llm_retries attempts; every attempt is recorded.
    Each attempt is bounded by min(cfg.llm_call_timeout_s, time left in the case budget). A timed
    out attempt's worker thread cannot be killed; it is abandoned and its result discarded.

    Side channels for the pipeline (no domain.py change needed):
    - `llm_flags`: (step, reason) for every step where the model reported suspicious content.
      Pass `llm_flag=budget.suspicious_flag` to intake.suspicious.detect (R-14: LOW alone).
    - `note_conflict`: the map_claims step saw a free-text note that may conflict with the ledger.
      Pass `llm_note_flag=budget.note_conflict` to rules.outcome.decide (R-08/R-10).
    """

    def __init__(self, client: LlmClient, cfg, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, backoff_s: float = 1.0):
        self.client = client
        self.cfg = cfg
        self._clock = clock
        self._sleep = sleep
        self.backoff_s = backoff_s
        self._start = clock()
        self._calls = 0
        self._records: list[LlmCallRecord] = []
        self.llm_flags: list[tuple[str, str]] = []
        self.note_conflict: bool = False
        self.note_conflict_reason: str = ""

    # -- accounting
    @property
    def records(self) -> list[LlmCallRecord]:
        return list(self._records)

    @property
    def calls_made(self) -> int:
        return self._calls

    @property
    def calls_left(self) -> int:
        return max(0, self.cfg.llm_max_calls_per_case - self._calls)

    def elapsed(self) -> float:
        return self._clock() - self._start

    def remaining_s(self) -> float:
        return self.cfg.llm_case_budget_s - self.elapsed()

    @property
    def cost_usd(self) -> float:
        return round(sum(r.cost_usd for r in self._records), 8)

    @property
    def tokens(self) -> tuple[int, int]:
        return (sum(r.tokens_in for r in self._records), sum(r.tokens_out for r in self._records))

    @property
    def suspicious_flag(self) -> bool:
        return bool(self.llm_flags)

    def flag_suspicious(self, step: str, reason: str) -> None:
        self.llm_flags.append((step, (reason or "")[:200]))

    def can_call(self) -> bool:
        return self.calls_left > 0 and self.remaining_s() > 0

    # -- the call
    def call(self, prompt_template_id: str, data: dict, schema: dict) -> dict:
        if self._calls >= self.cfg.llm_max_calls_per_case:
            raise LlmUnavailable(f"call cap {self.cfg.llm_max_calls_per_case} reached before {prompt_template_id}")
        self._calls += 1
        attempts = 1 + max(0, int(self.cfg.llm_retries))
        last_err = "unknown"
        for attempt in range(1, attempts + 1):
            remaining = self.remaining_s()
            if remaining <= 0:
                raise LlmUnavailable(f"case budget {self.cfg.llm_case_budget_s}s exhausted ({last_err})")
            timeout = min(self.cfg.llm_call_timeout_s, remaining)
            t0 = self._clock()
            try:
                out, rec = self._attempt(prompt_template_id, data, schema, timeout)
                validate_output(out, schema)   # defence in depth: never trust the client's check
                self._records.append(_with_attempt(rec, attempt))
                return out
            except ModelMismatch as e:
                self._records.append(_with_attempt(getattr(e, "record", None) or self._err_rec(
                    prompt_template_id, data, str(e), t0), attempt))
                raise
            except _Timeout:
                last_err = f"timeout after {timeout:.1f}s"
                self._records.append(self._err_rec(prompt_template_id, data, last_err, t0, attempt))
            except LlmCallError as e:
                last_err = str(e)
                rec = e.record or self._err_rec(prompt_template_id, data, last_err, t0)
                self._records.append(_with_attempt(rec, attempt))
            except Exception as e:  # any client bug is a failed attempt, not a crash
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                self._records.append(self._err_rec(prompt_template_id, data, last_err, t0, attempt))
            if attempt < attempts:
                wait = self.backoff_s * (2 ** (attempt - 1))
                if self.remaining_s() - wait <= 0:
                    raise LlmUnavailable(f"no time left for retry of {prompt_template_id} ({last_err})")
                self._sleep(wait)
        raise LlmUnavailable(f"{prompt_template_id} failed after {attempts} attempts ({last_err})")

    def _attempt(self, tid, data, schema, timeout):
        ex = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-call")
        fut = ex.submit(self.client.complete_json, tid, data, schema)
        try:
            return fut.result(timeout=timeout)
        except cf.TimeoutError:
            fut.cancel()
            raise _Timeout() from None
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    def _err_rec(self, tid, data, err, t0, attempt=1) -> LlmCallRecord:
        try:
            h = load_template(tid)[2]
        except Exception:
            h = ""
        return LlmCallRecord(model_id=getattr(self.client, "model_id", "?"), prompt_template_id=tid,
                             prompt_sha256=h, input_sha256s=input_hashes(data), output=None, error=err,
                             latency_ms=int((self._clock() - t0) * 1000), tokens_in=0, tokens_out=0,
                             cost_usd=0.0, attempt=attempt)


class _Timeout(Exception):
    pass


def _with_attempt(rec: LlmCallRecord, attempt: int) -> LlmCallRecord:
    from dataclasses import replace
    return rec if rec.attempt == attempt else replace(rec, attempt=attempt)


def make_client(backend: str, cfg, **kw) -> LlmClient:
    """'offline' (default, deterministic, no network) or 'anthropic' (pinned cfg.llm_model_id)."""
    if backend == "offline":
        return OfflineLlmClient(prices=kw.get("prices"))
    if backend == "anthropic":
        return AnthropicLlmClient(cfg, **kw)
    raise ValueError(f"unknown LLM backend {backend!r} (expected 'offline' or 'anthropic')")


def make_budget(client: LlmClient, cfg, **kw) -> CaseBudget:
    """Convenience for workflow Deps.make_budget."""
    return CaseBudget(client, cfg, **kw)
