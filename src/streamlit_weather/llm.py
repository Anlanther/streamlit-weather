"""LLM interaction for the grounded chat, backed by a local LM Studio server.

LM Studio exposes an OpenAI-compatible ``/v1`` API, so the official ``openai``
client is reused with a custom ``base_url``. Kept free of Streamlit so it can be
unit-tested and reused.

Configuration (environment variables):

========================  ============================  ================================
Variable                  Default                       Purpose
========================  ============================  ================================
``LM_STUDIO_BASE_URL``    ``http://localhost:1234/v1``  Where the LM Studio server listens
``LM_STUDIO_MODEL``       *(auto-detected)*             Model id to request; discovered
                                                        from ``/v1/models`` when unset
``LM_STUDIO_API_KEY``     ``lm-studio``                 Key sent to LM Studio; override if
                                                        your server validates it
========================  ============================  ================================

Values are read from the process environment, with a local ``.env`` file
(see ``.env.example``) as a fallback for anything not already set.
"""

from streamlit_weather import config

DEFAULT_BASE_URL = "http://localhost:1234/v1"

# LM Studio's fault-tolerant server accepts any non-empty key, and the
# ``openai`` client refuses to send a request without one. Override with
# ``LM_STUDIO_API_KEY`` when fronting a server that validates keys.
DEFAULT_API_KEY = "lm-studio"

GROUNDING_RULES = (
    "You are a helpful assistant for the Hong Kong Weather Dashboard. "
    "Answer ONLY using the provided forecast and warning data. "
    "If the answer is not in the data, say you don't have that information. "
    "Do not use outside knowledge, do not guess, and do not invent numbers. "
    "Cite specific dates and values when you answer, and keep replies concise."
)

# Number of prior turns replayed to the model (bounds prompt growth).
MAX_HISTORY_MESSAGES = 12


def base_url() -> str:
    """Resolve the LM Studio API root, normalising a trailing slash."""
    url = config.env("LM_STUDIO_BASE_URL", DEFAULT_BASE_URL)
    return url.rstrip("/")


def unavailable_message(reason: str) -> str:
    """User-facing notice explaining why chat cannot run.

    Mentions configuration rather than echoing raw connection errors, which are
    long and unhelpful for a reviewer who simply has not started LM Studio.
    """
    return (
        f"⚠️ Chat is unavailable: {reason}\n\n"
        f"Start a model in LM Studio and enable the local server, then check "
        f"`LM_STUDIO_BASE_URL` (currently `{base_url()}`)."
    )


def api_key() -> str:
    """Resolve the API key sent to LM Studio (defaults to the placeholder)."""
    return config.env("LM_STUDIO_API_KEY", DEFAULT_API_KEY)


def get_client(base: str | None = None):
    """Return an OpenAI-compatible client aimed at LM Studio, or ``None`` if import fails."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    return OpenAI(base_url=base or base_url(), api_key=api_key())


def resolve_model(client) -> str | None:
    """Return the model id to use.

    An explicit ``LM_STUDIO_MODEL`` always wins; otherwise the first model the
    server reports is used, because LM Studio model ids are arbitrary local
    paths that cannot be guessed in advance.
    """
    configured = config.env("LM_STUDIO_MODEL")
    if configured:
        return configured

    try:
        models = client.models.list()
    except Exception:
        # Most commonly the server is not running; the caller reports a generic
        # "no model" message, which is accurate either way.
        return None

    for model in getattr(models, "data", []) or []:
        model_id = getattr(model, "id", None)
        if model_id:
            return model_id
    return None


def build_messages(question: str, context: str, history: list[dict]) -> list[dict]:
    """Assemble a grounded chat-completion payload.

    ``history`` items are session-state dicts; locally generated error notices
    (``error: True``) are excluded so they are never fed back to the model.
    """
    system_prompt = f"{GROUNDING_RULES}\n\n--- PROVIDED DATA ---\n{context}\n--- END DATA ---"
    messages = [{"role": "system", "content": system_prompt}]
    turns = [
        {"role": past["role"], "content": past["content"]}
        for past in history
        if past.get("role") in {"user", "assistant"} and not past.get("error")
    ]
    messages.extend(turns[-MAX_HISTORY_MESSAGES:])
    messages.append({"role": "user", "content": question})
    return messages


def answer(question: str, context: str, history: list[dict], client=None) -> tuple[str, bool]:
    """Ask the local model a grounded question.

    Returns ``(text, is_error)``; ``is_error`` marks failures (server down, no
    model loaded, request error) rather than genuine model output, so the UI can
    avoid showing a grounding context that never produced an answer.
    """
    client = client or get_client()
    if client is None:
        return unavailable_message("the `openai` package is not installed."), True

    model = resolve_model(client)
    if not model:
        return unavailable_message("no model is loaded in LM Studio."), True

    try:
        response = client.chat.completions.create(
            model=model,
            messages=build_messages(question, context, history),
            temperature=0,
        )
        content = response.choices[0].message.content
    except Exception as exc:  # connection refused, timeout, model unloaded, etc.
        return unavailable_message(f"the request to LM Studio failed ({exc})."), True

    return (content or "I don't have that information."), False
