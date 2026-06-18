import asyncio
import logging
import time
from functools import lru_cache
from pydantic import BaseModel
from ..config import settings

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None
_pacing_lock: asyncio.Lock | None = None
_last_request_started_at: float = 0.0
_quota_blocked_until: float = 0.0
_quota_block_reason: str = ""

# Exponential backoff schedule for upstream 429/529 rate-limit errors
# Increased to cover >60s total for TPM (Tokens Per Minute) resets
_BACKOFF_SECONDS = [5, 15, 30, 60]
_QUOTA_COOLDOWN_SECONDS = 15 * 60
_RATE_LIMIT_COOLDOWN_SECONDS = 2 * 60


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
    return _semaphore


def _get_pacing_lock() -> asyncio.Lock:
    global _pacing_lock
    if _pacing_lock is None:
        _pacing_lock = asyncio.Lock()
    return _pacing_lock


async def _pace_request() -> None:
    global _last_request_started_at
    async with _get_pacing_lock():
        wait_seconds = settings.llm_min_interval_seconds - (time.monotonic() - _last_request_started_at)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        _last_request_started_at = time.monotonic()


@lru_cache(maxsize=2)
def _get_client(model_type: str = "default"):
    from interlinked.core.clients.googleaiclient import GoogleAIClient

    # Map model type to actual model name
    model_name = settings.llm_model
    if model_type == "fast":
        model_name = "gemini-1.5-flash"  # Use flash for fast mode

    # FORCE flash for document auto-tagging to avoid timeout/TPM issues with pro
    model_name = "gemini-2.5-flash"

    if settings.llm_use_floodgate:
        try:
            return GoogleAIClient(model_name=model_name, use_floodgate=True)
        except Exception as e:
            logger.warning(f"Floodgate init failed: {e}, falling back to direct Gemini API")

    try:
        return GoogleAIClient(model_name=model_name, use_floodgate=False)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini client: {e}")
        _get_client.cache_clear()
        raise RuntimeError(
            f"Cannot initialize Gemini client. "
            f"Check network connection and API configuration. "
            f"Error: {type(e).__name__}: {e}"
        )


def _is_rate_limit(err: Exception) -> bool:
    msg = str(err).lower()
    # Add timeout and connection drops to _is_rate_limit so it also backs off instead of immediately failing
    return any(kw in msg for kw in (
        "rate-limit", "rate limit", "exhausted", "529", "resource_exhausted", "429", "too_many_request",
        "read timed out", "timeout", "connection aborted", "remotedisconnected", "remote end closed connection"
    ))


def _is_budget_exceeded(err: Exception) -> bool:
    msg = str(err).lower()
    return any(kw in msg for kw in (
        "daily cost allocation",
        "exceeds budget",
        "could go over budget",
        "hit your daily cost allocation",
    ))


class LLMQuotaExceededError(RuntimeError):
    """Raised when the upstream provider quota/budget is exhausted."""


class LLMRequestTimeoutError(RuntimeError):
    """Raised when one request times out without blocking later smaller retries."""


def _remaining_quota_cooldown_seconds() -> int:
    remaining = int(_quota_blocked_until - time.monotonic())
    return max(0, remaining)


def _activate_quota_circuit(reason: str, cooldown_seconds: int = _QUOTA_COOLDOWN_SECONDS) -> None:
    global _quota_blocked_until, _quota_block_reason
    _quota_blocked_until = time.monotonic() + cooldown_seconds
    _quota_block_reason = reason


def _quota_circuit_message() -> str:
    reason = _quota_block_reason or "Provider daily budget is exhausted."
    remaining = _remaining_quota_cooldown_seconds()
    return f"{reason} Skipping further Gemini calls for about {remaining}s."


class GenerationResult(BaseModel):
    text: str
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    total_tokens: int = 0


async def generate(prompt: str, model_type: str = "default") -> str:
    if time.monotonic() < _quota_blocked_until:
        raise LLMQuotaExceededError(_quota_circuit_message())

    client = _get_client(model_type)
    client.TIMEOUT = settings.llm_timeout_seconds
    client.MAX_RETRIES = -1
    loop = asyncio.get_event_loop()

    last_err: Exception | None = None
    for attempt, delay in enumerate([0, *_BACKOFF_SECONDS]):
        if delay:
            logger.warning(f"Gemini rate-limited, retrying in {delay}s (attempt {attempt}/{len(_BACKOFF_SECONDS)})")
            await asyncio.sleep(delay)
        try:
            async with _get_semaphore():
                await _pace_request()
                response = await loop.run_in_executor(None, client.get_response, prompt)
            if isinstance(response, str):
                return response
            content = getattr(response, "content", None)
            return content if isinstance(content, str) else str(response)
        except Exception as e:
            last_err = e
            if isinstance(e, asyncio.TimeoutError):
                raise LLMRequestTimeoutError(
                    f"LLM request timed out after {settings.llm_timeout_seconds:.0f}s."
                ) from e
            if _is_budget_exceeded(e):
                _activate_quota_circuit(str(e))
                logger.error("Gemini quota/budget exhausted. Opening cooldown circuit for %ss.", _QUOTA_COOLDOWN_SECONDS)
                raise LLMQuotaExceededError(_quota_circuit_message()) from e
            if not _is_rate_limit(e):
                raise
    _activate_quota_circuit(
        f"Gemini remained rate-limited after {len(_BACKOFF_SECONDS)} retries.",
        _RATE_LIMIT_COOLDOWN_SECONDS,
    )
    raise LLMQuotaExceededError(_quota_circuit_message()) from last_err


async def generate_with_metrics(prompt: str, model_type: str = "default") -> GenerationResult:
    text = await generate(prompt, model_type)
    return GenerationResult(text=text)
