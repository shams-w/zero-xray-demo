import os
import re
import time as _time
import requests



# =============================================================
# MODEL SELECTION
# =============================================================
# LocalLLM now talks to Ollama (https://ollama.com) running on your
# own machine, instead of downloading Hugging Face model weights
# inside this process. You control which model runs by pulling it
# in Ollama yourself, e.g.:
#
#   ollama pull qwen3:4b          <- ZERO X-RAY default: compact Qwen 3 model
#   ollama pull qwen2.5:7b        <- optional larger alternative
#   ollama pull llama3.1:8b       <- optional larger alternative
#
# Change OLLAMA_MODEL below (or set the OLLAMA_MODEL environment
# variable) to match whatever you pulled. The rest of the codebase
# never has to change: every agent talks to LocalLLM.generate(),
# not to Ollama directly. The deterministic baseline logic in each
# agent already guarantees a valid result even if the model's JSON
# is imperfect, so switching models only affects *how often* the
# AI's own suggestions get used instead of the baseline, not
# whether the pipeline works at all.
OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL",
    "qwen3:4b",
)

# Ollama's local HTTP API. Override with OLLAMA_HOST if Ollama runs
# on a different machine/port than the default local install.
OLLAMA_HOST = os.environ.get(
    "OLLAMA_HOST",
    "http://localhost:11434",
)

# =============================================================
# MODE (real Ollama vs. the standalone mock server used for testing)
# =============================================================
# ZX_LLM_MODE is purely an explicit, human-readable label for which
# server OLLAMA_HOST is expected to point at -- it does NOT change
# how requests are made or parsed in any way; that would defeat the
# point of the mock server, which exists specifically to exercise
# the REAL request/response/parsing code path below against a
# lightweight FastAPI stand-in instead of a real model (see
# tools/mock_ollama_server.py). Switching between real Ollama and the
# mock therefore requires ZERO changes to any agent: only two
# environment variables move (ZX_LLM_MODE, OLLAMA_HOST) -- see
# .env.example for the exact REAL/MOCK variable pairs.
#
# ai_label() is the single place "analysis_source" strings are
# decided when the AI path succeeds, so every agent reports
# "MOCK_AI" (not "ai") whenever it was actually talking to the mock
# server -- this is what section 10 of the audit task requires
# ("Never hide AI failure" / distinguish AI vs MOCK_AI vs FALLBACK),
# implemented once here instead of duplicated per agent.
ZX_LLM_MODE = os.environ.get("ZX_LLM_MODE", "ollama").strip().lower()
IS_MOCK = ZX_LLM_MODE == "mock"
IS_GROQ = ZX_LLM_MODE == "groq"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b").strip()
GROQ_BASE_URL = os.environ.get(
    "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
).rstrip("/")

# Groq Free/Developer tiers enforce output-token-per-minute limits.
# Keep the per-call budget conservative and, more importantly, retry
# transient 429 responses instead of poisoning the availability cache
# for the rest of a 9-agent analysis run. These are transport controls
# only: agent prompts, parsers, deterministic fallbacks and journey logic
# remain unchanged.
GROQ_MAX_OUTPUT_TOKENS = max(1, int(os.environ.get("GROQ_MAX_OUTPUT_TOKENS", "900")))
GROQ_RATE_LIMIT_RETRIES = max(0, int(os.environ.get("GROQ_RATE_LIMIT_RETRIES", "4")))
GROQ_RATE_LIMIT_MAX_WAIT_SECONDS = max(1.0, float(
    os.environ.get("GROQ_RATE_LIMIT_MAX_WAIT_SECONDS", "65")
))

# =============================================================
# MANDATORY AI MODE (root-cause fix -- Ollama availability)
# =============================================================
# ZERO X-RAY's AI-dependent operations (Analyze above all -- the
# stages that do real semantic/journey reasoning) must not silently
# complete on deterministic fallback and be reported as a successful
# AI analysis when Ollama is genuinely unreachable. REQUIRE_OLLAMA
# defaults to True (Mandatory AI Mode is the default), and is what
# main.py's /api/analyze consults to STOP immediately with
# AI_ENGINE_UNAVAILABLE instead of running the pipeline at all. This
# does NOT remove or disable any agent's existing deterministic
# fallback code -- see LocalLLM.generate()'s own short-circuit below,
# which applies regardless of this flag and is a pure efficiency fix
# (skip a doomed network call once we already know Ollama is down),
# never a behavior change to any agent's fallback contract. Set
# REQUIRE_OLLAMA=false only to intentionally restore the old
# "always attempt, always fall back silently" behavior (e.g. a
# constrained dev sandbox with no Ollama installed at all).
REQUIRE_OLLAMA = os.environ.get("REQUIRE_OLLAMA", "true").strip().lower() not in (
    "false", "0", "no", "off",
)


class AIEngineUnavailableError(RuntimeError):
    """Raised when Ollama (or the configured model) is unreachable and
    REQUIRE_OLLAMA is in effect. `.code` is the stable, structured
    error identifier callers (main.py) surface to the client;
    `.reason` is the specific, human-readable diagnostic (connection
    error text, or "model not found", etc.)."""

    code = "AI_ENGINE_UNAVAILABLE"

    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"{self.code}: {reason}")


# How long a single availability check result is trusted before the
# next check re-verifies against Ollama for real (root-cause fix --
# "one centralized availability check/state so unavailable Ollama
# does not cause many long timeout calls"). Short enough that a
# genuinely recovered/restarted Ollama is picked back up quickly;
# long enough that a single /api/analyze run (many agents, many
# generate() calls) or a Challenge run (many internal simulation
# cases) performs at most one real reachability round trip instead of
# one per call site. Overridable for tests that need to observe a
# state change sooner.
AI_AVAILABILITY_CACHE_SECONDS = float(
    os.environ.get("ZX_AI_AVAILABILITY_CACHE_SECONDS", "10")
)


def log_raw_response(tag, response, limit=2500):
    """Print the verbatim raw text Ollama returned for a given agent
    call, BEFORE any JSON parsing/validation is attempted.

    This is the single most important diagnostic for "the AI call
    succeeded but the agent still fell back": every previous fallback
    message only said *that* parsing/validation failed, never *what*
    the model actually said, so a real qwen3:4b response that was
    subtly wrong (wrong shape, ids embedded in prose, a truncated
    tail) was invisible in the logs. Every agent that talks to the LLM
    should call this immediately after LocalLLM.generate() returns and
    before extract_json()/validation runs, so the exact raw text is on
    record for whichever branch (accepted / repaired / fallback) runs
    next.

    `tag` should identify the agent + call, e.g. "SERVICE.semantic_steps".
    Output is capped (default 2500 chars) so one pathological response
    can't flood the log; the cap is generous enough to show a full
    truncated-JSON tail for diagnosis.
    """
    text = str(response or "")
    if not text:
        print(f"[LLM RAW] [{tag}] <empty response>")
        return
    shown = text if len(text) <= limit else (text[:limit] + f"...<+{len(text) - limit} chars truncated>")
    print(f"[LLM RAW] [{tag}] ({len(text)} chars):\n{shown}")


def ai_label():
    """The analysis_source value an agent should record when its AI
    call succeeded -- "MOCK_AI" when talking to the mock server
    (ZX_LLM_MODE=mock), "ai" for a real Ollama call. A failed/
    unavailable call never uses this: agents fall back to "template"
    (or "unavailable") on their own, independent of this function."""
    return "MOCK_AI" if IS_MOCK else "ai"

# Default cap used only when a caller does not pass max_new_tokens at
# all. Individual agents doing heavier reasoning (full journey design,
# detailed per-step explanations, compliance/validation reasoning)
# should pass their own, larger max_new_tokens explicitly — this
# module no longer clamps every call down to a fixed ceiling.
DEFAULT_MAX_NEW_TOKENS = int(
    os.environ.get("OLLAMA_DEFAULT_MAX_NEW_TOKENS", "400")
)

# Some agents (full journey generation with detailed explanations for
# every step) legitimately need a long response. Give generate() a
# timeout that scales with how much output was requested instead of a
# single fixed 120s for every call, so a deliberately large
# max_new_tokens request doesn't get cut off by an unrelated network
# timeout. Still overridable per-call.
DEFAULT_TIMEOUT_SECONDS = int(
    os.environ.get("OLLAMA_DEFAULT_TIMEOUT_SECONDS", "120")
)

# ---------------------------------------------------------------
# CONTEXT WINDOW (root-cause fix)
# ---------------------------------------------------------------
# Ollama does NOT auto-size the context window to fit a request.
# Unless "num_ctx" is sent explicitly, it falls back to the
# model's default (commonly 2048 tokens for a locally pulled
# qwen3:4b). num_predict (the output budget) is reserved INSIDE
# that same window, alongside the prompt tokens. Agents in this
# codebase send fairly long system+user prompts (full numbered
# journey steps, often in Arabic, which tokenizes less densely)
# AND ask for large outputs (up to num_predict=1400 for the
# semantic-steps call). Prompt + num_predict routinely exceeds a
# 2048-token window, so Ollama has no room left to generate any
# tokens at all: it still returns HTTP 200 with a perfectly valid
# JSON body, just with message.content == "" and
# done_reason == "length" / eval_count == 0. That looks exactly
# like "the AI returned an empty response" even though the
# request, the connection, and the JSON parsing were all fine —
# which is why this was previously invisible: no exception is
# raised anywhere, so only the caller's generic fallback message
# ever printed.
#
# Qwen 3 4B supports a large context window, so there is plenty
# of headroom — we just have to ask Ollama to actually use it.
# Sized generously above any single call's max_new_tokens plus a
# realistic prompt, with a floor and a ceiling; per-call size still
# scales this up further for very large requests.
OLLAMA_NUM_CTX = int(
    os.environ.get("OLLAMA_NUM_CTX", "4096")
)

# Ceiling the one-shot retry (below) is allowed to grow up to when the
# starting OLLAMA_NUM_CTX turns out too small for a given prompt. Kept
# separate from OLLAMA_NUM_CTX itself so the *default*/steady-state
# window can stay small on low-memory machines while still letting a
# rare oversized prompt succeed instead of permanently and silently
# falling back to the deterministic baseline. Override with
# OLLAMA_MAX_NUM_CTX if the host has enough RAM/VRAM to go higher (or
# lower it, e.g. to the same value as OLLAMA_NUM_CTX, to keep the old
# "never grow" behavior on a genuinely memory-constrained machine).
OLLAMA_MAX_NUM_CTX = int(
    os.environ.get("OLLAMA_MAX_NUM_CTX", "8192")
)

# ROOT-CAUSE FIX: never let this client's outbound calls to Ollama be
# routed through any HTTP/HTTPS proxy (environment variables
# HTTP_PROXY/HTTPS_PROXY, or a Windows system/registry proxy). Ollama
# is always a local service (OLLAMA_HOST defaults to
# http://localhost:11434), so a proxy should never be involved for
# these calls under any circumstance -- if one is configured on the
# machine for unrelated reasons (corporate network policy, VPN
# software, some antivirus/DLP products that install a local
# inspecting proxy), `requests` may still pick it up by default
# (its Session objects default to trust_env=True, meaning they
# consult environment variables AND, on Windows, the registry proxy
# settings for every request). This explicit `proxies={"http": None,
# "https": None}` unconditionally overrides that, forcing a direct
# connection regardless of any proxy configuration present.
#
# This specifically explains a failure signature where curl.exe /
# PowerShell's Invoke-RestMethod (which use Windows' native WinINET
# proxy resolution, honoring the "bypass proxy for local addresses"
# setting reliably) succeed against the exact same URL and payload
# that `requests.post()` 404s on: a proxy sitting in front of the
# Python process's traffic can return its own 404 for a POST with a
# JSON body (many corporate/security proxies inspect or restrict
# POST differently from GET) while still letting a simple GET
# through -- matching the observed "/api/tags works, /api/chat 404s"
# pattern exactly.
_NO_PROXY = {"http": None, "https": None}


def _normalize_host(value):
    """Strip a trailing slash so f"{host}/api/chat" can never become
    a double slash (".../11434//api/chat"), which some HTTP routers
    treat as a distinct, unregistered route and 404 on -- independent
    of the proxy issue above, and worth guarding against regardless
    of how OLLAMA_HOST ends up set (manually exported, from a stray
    .env value, etc.)."""
    return str(value or "").rstrip("/")


OLLAMA_HOST = _normalize_host(OLLAMA_HOST)


def estimate_tokens(text):
    """Rough token-count estimate for a piece of prompt text.

    ROOT-CAUSE NOTE: chars/3 is only a safe upper bound for
    mostly-ASCII English text. It is NOT safe for Arabic: BPE
    tokenizers (qwen2.5 included) were trained overwhelmingly on
    Latin-script text, so non-Latin characters routinely cost close to
    (sometimes more than) 1 token PER CHARACTER instead of the ~3-4
    chars/token that chars/3 assumes. Count non-ASCII characters
    (Arabic, and any other non-Latin script) at a much heavier ~1.3
    chars/token instead of ~3.5.

    Pulled out to module level (was previously a closure inside
    LocalLLM.generate()) so the exact same estimate used for real
    token-budget decisions can also be exercised directly by tests,
    instead of only indirectly through a live/mocked HTTP call.
    """
    text = str(text or "")
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    ascii_chars = len(text) - non_ascii
    return int(ascii_chars / 3.5) + int(non_ascii / 1.3)


def detect_language_mismatch(value, expected_lang, min_alpha_chars=20):
    """Cheap, false-positive-resistant check for an obviously wrong output
    language -- e.g. an Arabic-requested field that came back almost
    entirely in English, or vice versa.

    Reuses the same Arabic-range detection already used elsewhere in this
    codebase (agents/journey_builder_agent.py's _is_arabic,
    agents/step_compliance_agent.py) rather than adding a language-detection
    library: no new dependency, same battle-tested character-range check.

    Deliberately a RATIO over alphabetic characters, not "any word in the
    other script" -- real generated text legitimately contains proper
    nouns, brand names and technical terms in the other script (UAE PASS,
    EMX, Swagger/OpenAPI, service IDs) without that being a language
    mismatch. Only flags the case where the requested-language script is a
    small minority of the alphabetic content, which a few loanwords never
    triggers on their own. Ignores strings under min_alpha_chars: too short
    for a ratio to mean anything, and avoids flagging isolated proper nouns.

    Returns True only on a clear, actionable mismatch; False for anything
    ambiguous or too short to judge -- silence is the safe default here,
    since this feeds a decision (log/retry), not just an assertion.
    """
    text = str(value or "")
    arabic_chars = sum(1 for ch in text if "\u0600" <= ch <= "\u06ff")
    latin_chars = sum(1 for ch in text if ch.isalpha() and ch.isascii())
    total_alpha = arabic_chars + latin_chars
    if total_alpha < min_alpha_chars:
        return False
    if expected_lang == "ar":
        return (arabic_chars / total_alpha) < 0.3
    if expected_lang == "en":
        return (latin_chars / total_alpha) < 0.7
    return False


def _headroom_for(ctx):
    # Reserve room for tokenizer-estimation error (Arabic/non-Latin
    # text is estimated, not measured exactly).
    return max(384, int(ctx * 0.10))


def resolve_context_budget(
    estimated_prompt_tokens,
    max_new_tokens,
    base_num_ctx=None,
    max_num_ctx=None,
):
    """Decide (num_ctx, effective_max_new_tokens) for a single Ollama
    call, given an estimated prompt size and the caller's requested
    output size.

    ROOT-CAUSE FIX: this used to treat the steady-state num_ctx
    (OLLAMA_NUM_CTX, default 4096) as fixed and, whenever prompt +
    requested output didn't fit inside it, silently SHRANK the output
    budget down to a 256-token floor to make it fit. That is
    backwards: a caller asks for max_new_tokens because that is
    roughly how much JSON the task actually needs (e.g. the Standards
    agent selecting from and justifying against a 15-entry catalog) --
    capping it to 256 tokens doesn't make the model answer faster, it
    just guarantees the JSON is cut off before it can include every
    relevant id. This was the exact observed failure signature:
    "estimated_prompt=3534, num_ctx=4096 -> output forced down to
    256" produced a real, valid-looking JSON response that was simply
    too short to contain the model's actual answer.

    The fix: try to GROW num_ctx (up to max_num_ctx) so the requested
    output budget still fits, instead of shrinking the output budget
    to fit a fixed window. Only if the prompt is so large that even
    the ceiling can't fit the requested output do we fall back to
    trimming the output budget -- and even then we trim to whatever
    the ceiling *can* fit, rather than an arbitrary fixed 256-token
    floor.

    Pulled out as a standalone, side-effect-free function (previously
    inline in LocalLLM.generate()) specifically so this budgeting
    decision can be unit-tested directly, without needing a live or
    mocked HTTP round trip.

    Returns (num_ctx, effective_max_new_tokens, note) where `note` is
    either None or a human-readable string the caller should log --
    kept as a return value rather than a print() here so this function
    has no side effects of its own.
    """
    base_num_ctx = OLLAMA_NUM_CTX if base_num_ctx is None else base_num_ctx
    max_num_ctx = OLLAMA_MAX_NUM_CTX if max_num_ctx is None else max_num_ctx

    required_ctx = estimated_prompt_tokens + max_new_tokens + _headroom_for(base_num_ctx)

    if required_ctx <= base_num_ctx:
        return base_num_ctx, max_new_tokens, None

    # Grow num_ctx to fit the full requested output. Headroom itself
    # scales with num_ctx (10%), so a single min(max_num_ctx,
    # required_ctx) computed against the SMALLER base-ctx headroom can
    # undershoot once the larger window's own (larger) headroom is
    # applied -- fixed-point iterate a few times (converges
    # immediately in practice) instead of shrinking output that
    # growth was actually meant to avoid.
    grown_ctx = required_ctx
    for _ in range(4):
        candidate = min(
            max_num_ctx,
            estimated_prompt_tokens + max_new_tokens + _headroom_for(grown_ctx),
        )
        if candidate == grown_ctx:
            break
        grown_ctx = candidate
    grown_ctx = min(max_num_ctx, grown_ctx)

    note = None
    if grown_ctx > base_num_ctx:
        note = (
            f"[LLM] Prompt ({estimated_prompt_tokens} est. tokens) "
            f"+ requested output ({max_new_tokens} tokens) exceeds "
            f"the default num_ctx={base_num_ctx}. Growing num_ctx to "
            f"{grown_ctx} (ceiling={max_num_ctx}) instead of shrinking "
            "the requested output."
        )

    available_output_tokens = max(
        256,
        grown_ctx - estimated_prompt_tokens - _headroom_for(grown_ctx),
    )
    effective_max_new_tokens = min(max_new_tokens, available_output_tokens)
    if effective_max_new_tokens < max_new_tokens:
        shrink_note = (
            f"[LLM] Low-memory token budget even at the num_ctx "
            f"ceiling ({grown_ctx}): requested={max_new_tokens}, "
            f"using={effective_max_new_tokens}, estimated_prompt="
            f"{estimated_prompt_tokens}. Raise OLLAMA_MAX_NUM_CTX if "
            "the host has enough memory to go higher."
        )
        note = f"{note}\n{shrink_note}" if note else shrink_note

    return grown_ctx, effective_max_new_tokens, note


class LocalLLM:

    def _ensure_runtime_state(self):
        """Initialize per-instance runtime state for all construction paths."""
        if not hasattr(self, "_availability_cache"):
            self._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
        if not hasattr(self, "_connectivity_failure_this_run"):
            self._connectivity_failure_this_run = False

    def __init__(self):

        if IS_GROQ:
            print(f"Connecting to Groq (model: {GROQ_MODEL}, mode: CLOUD)...")
        else:
            print(
                f"Connecting to Ollama at {OLLAMA_HOST} "
                f"(model: {OLLAMA_MODEL}, mode: "
                f"{'MOCK' if IS_MOCK else 'REAL'})..."
            )

        # Centralized availability state (root-cause fix -- "one
        # centralized availability check/state" instead of every
        # agent/call site independently discovering Ollama is down).
        # `None` means "never checked yet"; check_available() below is
        # the only place these are written.
        self._availability_cache = {"available": None, "reason": None, "checked_at": 0.0}
        # Set for the duration of a single request/run by main.py
        # (reset_run_failure_tracking) and read after orchestrator.
        # analyze() returns to decide whether to abort-and-discard
        # instead of save (Section 1 audit fix, requirement 4). Only a
        # genuine connectivity-level failure (connection refused/
        # timeout/DNS/non-200) sets this -- never a parse/empty-content
        # model-quality issue, which keeps using its existing,
        # unchanged, honestly-labeled deterministic fallback.
        self._connectivity_failure_this_run = False

        # Fail fast with a clear message instead of a confusing
        # connection error deep inside the first agent call. This
        # does NOT download anything — it only checks that the
        # Ollama service is reachable and know about the model. Also
        # seeds the availability cache so the very first request
        # doesn't have to perform this round trip again.
        available, reason = self.check_available(force=True)
        if not available:
            print(
                f"[LLM] Warning: {reason} AI-assisted decisions will "
                f"fall back to each agent's deterministic default "
                f"until the configured AI provider is reachable."
            )

        print("AI provider connection check complete.")

    # =================================================================
    # CENTRALIZED AVAILABILITY CHECK (root-cause fix)
    # =================================================================

    def check_available(self, force=False):
        """Single, non-retrying reachability + model-presence check.

        Returns (available: bool, reason: str | None). `reason` is
        always a complete, human-readable sentence -- either why it's
        NOT available, or None when it is. Result is cached for
        AI_AVAILABILITY_CACHE_SECONDS so a whole /api/analyze run (or
        a Challenge run with dozens of internal simulation cases)
        performs at most one real HTTP round trip to Ollama's /api/tags
        for this, not one per generate() call -- this is the
        "centralized state" requirement 3 asks for. Pass force=True to
        bypass the cache and re-check immediately (used once at
        startup, and by main.py right before a mandatory-gated
        operation so a just-restarted Ollama is picked up promptly).
        """
        self._ensure_runtime_state()
        now = _time.monotonic()
        cache = self._availability_cache
        if not force and cache["available"] is not None:
            age = now - cache["checked_at"]
            if age < AI_AVAILABILITY_CACHE_SECONDS:
                return cache["available"], cache["reason"]

        if IS_GROQ:
            if not GROQ_API_KEY:
                reason = "GROQ_API_KEY is not configured."
                cache.update(available=False, reason=reason, checked_at=now)
                return False, reason
            try:
                response = requests.get(
                    f"{GROQ_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    timeout=10,
                )
                response.raise_for_status()
                models = [item.get("id", "") for item in response.json().get("data", [])]
            except requests.exceptions.RequestException as error:
                reason = f"Could not reach Groq ({error})."
                cache.update(available=False, reason=reason, checked_at=now)
                return False, reason
            except ValueError as error:
                reason = f"Groq returned an unparseable response ({error})."
                cache.update(available=False, reason=reason, checked_at=now)
                return False, reason
            if GROQ_MODEL not in models:
                reason = f"Model '{GROQ_MODEL}' is not available from Groq."
                cache.update(available=False, reason=reason, checked_at=now)
                return False, reason
            cache.update(available=True, reason=None, checked_at=now)
            return True, None

        try:
            response = requests.get(
                f"{OLLAMA_HOST}/api/tags",
                timeout=5,
                proxies=_NO_PROXY,
            )
            response.raise_for_status()
            models = [
                item.get("name", "")
                for item in response.json().get("models", [])
            ]
        except requests.exceptions.RequestException as error:
            reason = f"Could not reach Ollama at {OLLAMA_HOST} ({error})."
            cache.update(available=False, reason=reason, checked_at=now)
            return False, reason
        except ValueError as error:
            reason = f"Ollama at {OLLAMA_HOST} returned an unparseable response ({error})."
            cache.update(available=False, reason=reason, checked_at=now)
            return False, reason

        if not any(
            OLLAMA_MODEL in name or name.startswith(OLLAMA_MODEL)
            for name in models
        ):
            reason = (
                f"Model '{OLLAMA_MODEL}' was not found in Ollama's local "
                f"model list {models}. Run `ollama pull {OLLAMA_MODEL}` "
                f"first, or set the OLLAMA_MODEL env var to a model you "
                f"already pulled."
            )
            cache.update(available=False, reason=reason, checked_at=now)
            return False, reason

        cache.update(available=True, reason=None, checked_at=now)
        return True, None

    def reset_run_failure_tracking(self):
        """Call once at the start of a mandatory-gated operation (see
        main.py's /api/analyze) so had_connectivity_failure_this_run
        reflects only what happens during THIS run, not a previous
        one."""
        self._ensure_runtime_state()
        self._connectivity_failure_this_run = False

    @property
    def had_connectivity_failure_this_run(self):
        self._ensure_runtime_state()
        return self._connectivity_failure_this_run

    def generate(
        self,
        system_prompt,
        user_prompt,
        max_new_tokens=None,
        temperature=0,
        timeout=None,
    ):
        """Call Ollama and return the raw text response.

        max_new_tokens is no longer silently clamped to a fixed
        ceiling. Callers doing light classification can pass a small
        value (or omit it, which uses DEFAULT_MAX_NEW_TOKENS); callers
        that need a genuinely detailed, multi-paragraph response (a
        full future-journey design with a rich explanation per step,
        a redesign rationale, a compliance judgement) should pass a
        larger max_new_tokens explicitly so the model isn't cut off
        mid-explanation.

        timeout scales with the requested output size by default so a
        deliberately long generation doesn't get killed by a timeout
        sized for short responses; pass timeout explicitly to override.

        Every agent that calls generate() already has a safe
        deterministic fallback for when the AI is unavailable, times
        out, or its output can't be parsed — this method returns ""
        on any failure so that fallback path kicks in uniformly,
        exactly as it does for a malformed AI response.
        """
        # ROOT-CAUSE FIX (requirement 3 -- "no repeated long retries"):
        # if we already know, from the centralized cache, that Ollama
        # is unreachable, don't attempt yet another doomed network
        # call -- just return "" immediately, exactly the same value
        # this method already returns on a real connection failure.
        # This is a pure efficiency fix: it changes nothing about any
        # agent's fallback behavior or output (every agent already
        # treats "" as "AI failed, use the deterministic default"),
        # it only avoids one wasted HTTP attempt per call site across
        # a 9-stage /api/analyze run or a Challenge run with dozens of
        # internal simulation cases. Only skips when we have a cached
        # answer already (check_available() with the default,
        # non-forcing cache) -- never blocks generate() on a fresh
        # network round trip of its own.
        self._ensure_runtime_state()
        cached_available = self._availability_cache["available"]
        if cached_available is False:
            reason = self._availability_cache["reason"]
            print(f"[LLM] Skipping call -- AI engine unavailable ({reason}). No request sent.")
            return ""

        if max_new_tokens is None:
            max_new_tokens = DEFAULT_MAX_NEW_TOKENS
        max_new_tokens = max(1, int(max_new_tokens))

        if timeout is None:
            # Scale generously with requested output length, with a
            # sane floor/ceiling so a tiny request isn't stuck with an
            # overlong timeout and a huge request isn't starved.
            timeout = max(
                DEFAULT_TIMEOUT_SECONDS,
                min(600, int(max_new_tokens / 4) + 60),
            )

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ]

        # Cloud production provider. Keep every agent prompt and every
        # downstream parser unchanged; only the transport/model host changes.
        if IS_GROQ:
            if not GROQ_API_KEY:
                print("[LLM] Groq call skipped: GROQ_API_KEY is not configured.")
                return ""

            groq_max_tokens = min(max_new_tokens, GROQ_MAX_OUTPUT_TOKENS)

            def _retry_after_seconds(response):
                """Return Groq's requested wait for a 429, capped safely.

                Groq normally sends Retry-After. Some responses also put
                phrases such as "try again in 34.02s" / "480ms" in the
                JSON error message. Parse either form so Free-tier throttling
                is handled deterministically without depending on one header.
                """
                raw = str(response.headers.get("Retry-After", "") or "").strip()
                try:
                    if raw:
                        return min(GROQ_RATE_LIMIT_MAX_WAIT_SECONDS, max(0.05, float(raw)))
                except (TypeError, ValueError):
                    pass

                text = str(getattr(response, "text", "") or "")
                match = re.search(
                    r"try\s+again\s+in\s+([0-9]+(?:\.[0-9]+)?)\s*(ms|s|sec|secs|seconds)?",
                    text,
                    flags=re.IGNORECASE,
                )
                if match:
                    value = float(match.group(1))
                    unit = (match.group(2) or "s").lower()
                    if unit == "ms":
                        value /= 1000.0
                    return min(GROQ_RATE_LIMIT_MAX_WAIT_SECONDS, max(0.05, value))

                # A conservative fallback when Groq omits both forms.
                return min(GROQ_RATE_LIMIT_MAX_WAIT_SECONDS, 5.0)

            for attempt in range(GROQ_RATE_LIMIT_RETRIES + 1):
                try:
                    print(
                        f"[LLM] Sending request to Groq (model={GROQ_MODEL}, "
                        f"max_tokens={groq_max_tokens}, timeout={timeout}s, "
                        f"attempt={attempt + 1}/{GROQ_RATE_LIMIT_RETRIES + 1})..."
                    )
                    response = requests.post(
                        f"{GROQ_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {GROQ_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": GROQ_MODEL,
                            "messages": messages,
                            "temperature": max(float(temperature), 1e-8),
                            "max_tokens": groq_max_tokens,
                            "response_format": {"type": "json_object"},
                            "reasoning_effort": "none",
                        },
                        timeout=timeout,
                    )

                    if response.status_code == 429:
                        wait_seconds = _retry_after_seconds(response)
                        print(
                            f"[LLM] Groq rate limit (429). Waiting "
                            f"{wait_seconds:.2f}s before retry. "
                            f"Response body: {response.text[:500]!r}"
                        )
                        if attempt < GROQ_RATE_LIMIT_RETRIES:
                            _time.sleep(wait_seconds)
                            continue
                        print(
                            "[LLM] Groq rate limit retries exhausted; "
                            "returning an empty response so the agent can use "
                            "its explicitly-labelled fallback."
                        )
                        return ""

                    if response.status_code != 200:
                        print(
                            f"[LLM] Non-200 from Groq: {response.status_code}. "
                            f"Response body: {response.text[:500]!r}"
                        )
                    response.raise_for_status()
                    data = response.json()
                    choices = data.get("choices") or []
                    if not choices:
                        print("[LLM] Groq returned no choices.")
                        return ""
                    message = choices[0].get("message") or {}
                    content = str(message.get("content", "") or "")
                    if not content:
                        print("[LLM] Groq returned an empty message content.")
                        return ""
                    return content
                except requests.exceptions.RequestException as error:
                    print(f"[LLM] Groq call failed: {error}")
                    # A real transport/provider outage is different from a
                    # transient 429. Only genuine connectivity failures poison
                    # the run-level availability state and cause mandatory-AI
                    # /api/analyze to abort without persisting a fake success.
                    self._connectivity_failure_this_run = True
                    self._availability_cache.update(
                        available=False, reason=f"Groq call failed: {error}",
                        checked_at=_time.monotonic(),
                    )
                    return ""
                except (ValueError, TypeError, KeyError) as error:
                    print(f"[LLM] Groq returned an unusable response: {error}")
                    return ""

        # The context window must fit BOTH the prompt tokens and the
        # requested output (num_predict). Without this, Ollama uses
        # its small default window and silently truncates/starves
        # generation instead of erroring — see OLLAMA_NUM_CTX above.
        #
        # ROOT-CAUSE FIX: chars/3 is only a safe upper bound for
        # mostly-ASCII English text. It is NOT safe for Arabic: BPE
        # tokenizers (qwen2.5 included) were trained overwhelmingly on
        # Latin-script text, so non-Latin characters routinely cost
        # close to (sometimes more than) 1 token PER CHARACTER instead
        # of the ~3-4 chars/token that chars/3 assumes. The two calls
        # that were failing in practice (service_agent's semantic-step
        # extraction, step_compliance_agent's per-step review) are
        # exactly the two whose prompts embed large blocks of the
        # user's own raw Arabic text; the calls that kept working
        # (journey_builder, validation) mostly echo back
        # already-templated/English-labelled JSON. Undercounting the
        # real token cost of an Arabic-heavy prompt means the computed
        # num_ctx can still be smaller than prompt + num_predict, so
        # Ollama returns HTTP 200 with message.content == "" and
        # done_reason == "length" — a genuinely valid response that
        # never had any room left to generate into. Count non-ASCII
        # characters (Arabic, and any other non-Latin script) at a
        # much heavier ~1.3 chars/token instead of 3.
        estimated_prompt_tokens = estimate_tokens(
            system_prompt
        ) + estimate_tokens(user_prompt)

        # STRUCTURED-OUTPUT TOKEN BUDGET (root-cause fix): see
        # resolve_context_budget()'s docstring for the full
        # explanation. In short: grow num_ctx to fit the requested
        # output instead of silently shrinking the output to fit a
        # fixed num_ctx.
        num_ctx, effective_max_new_tokens, budget_note = resolve_context_budget(
            estimated_prompt_tokens, max_new_tokens
        )
        if budget_note:
            print(budget_note)

        # ROOT-CAUSE FIX (perceived "hang" at a given stage, e.g.
        # "[4/9] Gap Analysis Agent..."): a caller only ever sees the
        # stage banner print once, then nothing, for as long as this
        # single call takes -- there was no line in between telling
        # anyone a request was actually in flight and roughly how
        # long it could legitimately run for. Against a real local
        # qwen3:4b on CPU, a call asking for ~2000+ output tokens at
        # num_ctx=8192 can legitimately take several minutes; with
        # nothing printed in that window it is indistinguishable from
        # a genuine deadlock, which is exactly what prompted restarts
        # in practice. This heartbeat does not change behavior, only
        # visibility.
        print(
            f"[LLM] Sending request to Ollama "
            f"(~{estimated_prompt_tokens} prompt tokens, up to "
            f"{effective_max_new_tokens} output tokens, num_ctx="
            f"{num_ctx}, timeout={timeout}s). Waiting for a response..."
        )

        def _call_ollama(num_ctx_value, call_timeout):
            url = f"{OLLAMA_HOST}/api/chat"
            headers = {}
            if IS_MOCK:
                # Only ever sent when explicitly running against the
                # mock server (ZX_LLM_MODE=mock). Real Ollama has no
                # such header and ignores unknown headers, so this is
                # completely inert against a real server. Lets one
                # running mock server instance simulate a different
                # failure mode per request (driven by the SAME
                # ZX_MOCK_FAILURE_MODE env var the mock server itself
                # also honors when set on its own process at startup)
                # instead of requiring a server restart per mode --
                # both usages are supported; see
                # tools/mock_ollama_server.py's _current_failure_mode.
                mock_failure_mode = os.environ.get("ZX_MOCK_FAILURE_MODE", "").strip()
                if mock_failure_mode:
                    headers["X-ZX-Mock-Failure-Mode"] = mock_failure_mode
            response = requests.post(
                url,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    # Qwen 3 enables thinking/reasoning by default in Ollama.
                    # ZERO X-RAY needs structured JSON in message.content; on
                    # low-memory machines the model could spend the whole
                    # num_predict budget on hidden thinking and return empty
                    # content with done_reason='length'. Disable thinking so
                    # the token budget is used for the actual JSON result.
                    "think": False,
                    # Ollama structured-output mode. All ZERO X-RAY agents
                    # consume JSON, so force the model to emit a JSON object
                    # instead of relying only on prompt wording. This is
                    # especially important for compact Qwen models, which can
                    # otherwise prepend prose or produce almost-JSON.
                    "format": "json",
                    "options": {
                        "num_predict": effective_max_new_tokens,
                        "temperature": temperature,
                        "num_ctx": num_ctx_value,
                    },
                },
                timeout=call_timeout,
                proxies=_NO_PROXY,
                headers=headers,
            )
            if response.status_code != 200:
                # DIAGNOSTIC: previously only the generic
                # "404 Client Error: Not Found for url: ..." from
                # requests' own exception message was visible, which
                # doesn't say what actually came back. Log the exact
                # URL requests sent to (proves/disproves any
                # trailing-slash or host-mismatch theory at a glance)
                # and the response body Ollama/whatever answered with,
                # before raising -- this is what makes a future
                # regression instantly diagnosable from the server log
                # alone instead of needing a fresh repro session.
                print(
                    f"[LLM] Non-200 from Ollama: POST {url} -> "
                    f"{response.status_code}. Response body: "
                    f"{response.text[:500]!r}"
                )
            response.raise_for_status()
            return response.json()

        try:
            data = _call_ollama(num_ctx, timeout)
        except requests.exceptions.RequestException as error:
            print(f"[LLM] Ollama call failed: {error}")
            # ROOT-CAUSE FIX (requirement 4 -- "abort cleanly... do not
            # save an incomplete operation as successful"): a genuine
            # connectivity-level failure here (connection refused,
            # timeout, DNS failure, or a non-200 status via
            # raise_for_status) means Ollama went from available to
            # unavailable DURING this run. Flag it so main.py's
            # /api/analyze can discard the result instead of saving it
            # -- never on a JSON-parse/empty-content issue, which is a
            # model-quality problem, not an availability one, and
            # keeps using its existing per-agent deterministic fallback
            # exactly as before (requirement 5).
            self._connectivity_failure_this_run = True
            # The cache may still say "available" from an earlier
            # check within its TTL window -- a live failure is more
            # current truth than a stale cache entry, so refresh it
            # immediately rather than waiting out the TTL.
            self._availability_cache.update(
                available=False, reason=f"Ollama call failed: {error}",
                checked_at=_time.monotonic(),
            )
            return ""
        except ValueError as error:
            # response.json() raises ValueError (json.JSONDecodeError
            # is a subclass) if Ollama's body isn't valid JSON. This
            # is not a requests.exceptions.RequestException, so it
            # needs its own guard to honor this method's own
            # documented contract: return "" on ANY failure so every
            # agent's fallback triggers uniformly, instead of an
            # unhandled exception crashing the whole pipeline.
            print(f"[LLM] Ollama returned an unparseable response: {error}")
            return ""

        if not isinstance(data, dict):
            print(
                "[LLM] Ollama returned an unexpected response shape "
                f"({type(data).__name__}), expected a JSON object."
            )
            return ""

        message = data.get("message", {})
        if not isinstance(message, dict):
            print(
                "[LLM] Ollama response had no usable 'message' object "
                f"(got {type(message).__name__}). Full body keys: "
                f"{list(data.keys())}."
            )
            return ""

        content = str(message.get("content", "") or "")

        if not content:
            done_reason = data.get("done_reason")
            eval_count = data.get("eval_count")
            print(
                "[LLM] Ollama returned HTTP 200 but with EMPTY "
                f"content. done_reason={done_reason!r}, "
                f"prompt_eval_count={data.get('prompt_eval_count')!r}, "
                f"eval_count={eval_count!r}, num_ctx_sent={num_ctx}."
            )

            # ROOT-CAUSE FIX (evidence-based retry, not a blind one):
            # done_reason == "length" with eval_count == 0 is the
            # unambiguous signature of "the context window was
            # exhausted by the prompt before a single output token
            # could be generated" — i.e. our own num_ctx estimate was
            # still too small for this specific prompt. This is not
            # network flakiness or a malformed response, it is a
            # provably wrong sizing decision made two paragraphs
            # above, on OUR side. Retry exactly once with a
            # substantially larger, explicit num_ctx so the diagnosis
            # is either confirmed fixed or the true remaining cause
            # (e.g. the host cannot allocate that much memory) becomes
            # visible in the log instead of being silently swallowed
            # into a generic "empty response" fallback message.
            if done_reason == "length" and eval_count == 0:
                # Root-cause fix, re-enabled: this used to be gated
                # behind `if False` (a leftover debug disable from
                # tracking down a low-memory CUDA OOM), which meant
                # the diagnostic above ran and printed a perfectly
                # correct root-cause explanation every time, but the
                # actual fix never executed -- every affected call
                # (Arabic-heavy prompts, mainly service_agent's
                # semantic-step extraction and step_compliance_agent's
                # per-step review) silently fell back to the
                # deterministic "template" baseline forever, even
                # with Ollama healthy and reachable. The retry ceiling
                # is now OLLAMA_MAX_NUM_CTX (separate from the
                # steady-state OLLAMA_NUM_CTX) so it can actually grow
                # past a 4096 starting window instead of being capped
                # right back down to the same value that just failed.
                retried_num_ctx = min(OLLAMA_MAX_NUM_CTX, num_ctx * 2)
                if retried_num_ctx > num_ctx:
                    # ROOT-CAUSE FIX: this retry used to reuse the
                    # SAME `timeout` as the first attempt (up to the
                    # 600s ceiling above), so a single generate() call
                    # could legitimately block for first+retry =
                    # up to ~1200s (20 minutes) with nothing in
                    # between to distinguish "still working" from
                    # "actually stuck" -- previous sessions raising
                    # the timeout constant only made this worse, not
                    # better, which is why "just increase the
                    # timeout" never fixed the reported hang. Bound
                    # the retry to a smaller, fixed budget instead of
                    # doubling an already-large timeout, so the
                    # worst case for one call is capped at
                    # `timeout + retry_timeout` (a few minutes, not
                    # twenty), and a genuinely dead Ollama process is
                    # discovered and reported quickly enough that the
                    # single-flight guard in main.py releases before
                    # a user gives up and restarts.
                    retry_timeout = min(timeout, 180)
                    print(
                        f"[LLM] Context-exhaustion signature detected "
                        f"(done_reason='length', eval_count=0). "
                        f"Retrying once with num_ctx={retried_num_ctx} "
                        f"(was {num_ctx}), retry_timeout={retry_timeout}s "
                        f"(capped, independent of the first attempt's "
                        f"{timeout}s timeout)."
                    )
                    try:
                        retry_data = _call_ollama(retried_num_ctx, retry_timeout)
                    except requests.exceptions.RequestException as error:
                        print(f"[LLM] Retry call failed: {error}")
                        self._connectivity_failure_this_run = True
                        self._availability_cache.update(
                            available=False, reason=f"Ollama retry call failed: {error}",
                            checked_at=_time.monotonic(),
                        )
                        return ""
                    except ValueError as error:
                        print(f"[LLM] Retry call failed: {error}")
                        return ""
                    retry_message = (
                        retry_data.get("message", {})
                        if isinstance(retry_data, dict) else {}
                    )
                    retry_content = str(
                        (retry_message or {}).get("content", "") or ""
                    )
                    if retry_content:
                        print(
                            "[LLM] Retry with larger num_ctx produced "
                            f"{len(retry_content)} chars of content — "
                            "confirms the original num_ctx was too "
                            "small for this prompt."
                        )
                        return retry_content
                    print(
                        "[LLM] Retry with num_ctx="
                        f"{retried_num_ctx} still returned empty "
                        f"content (done_reason="
                        f"{(retry_data or {}).get('done_reason')!r}). "
                        "This is not a context-sizing problem — check "
                        "that the Ollama host actually has enough "
                        "memory to load this model at this context "
                        "size."
                    )

        return content


