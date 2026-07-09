import asyncio
import json
import re
from typing import Type, TypeVar
from pydantic import BaseModel
from openai import AsyncOpenAI, RateLimitError, APIStatusError
from app.config import settings
import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

LONG_CONTEXT_THRESHOLD = 32_000  # tokens aprox


class AllProvidersExhausted(Exception):
    pass


class ProviderExhausted(Exception):
    """Raised when a provider is known (from a cached flag) to be out of
    daily quota — lets the caller skip straight to the next provider without
    a wasted network round-trip."""
    pass


class LLMClient:
    """
    Fallback chain: Groq (Llama 3.3 70B) → Gemini Flash → Ollama local.
    Siempre retorna objeto Pydantic validado. Nunca texto crudo.
    """

    def __init__(self):
        self._groq: AsyncOpenAI | None = None
        self._ollama: AsyncOpenAI | None = None
        self._gemini = None
        self.last_provider: str = "unknown"
        self.last_model: str = "unknown"

    @property
    def groq(self) -> AsyncOpenAI:
        if self._groq is None:
            self._groq = AsyncOpenAI(
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        return self._groq

    @property
    def ollama(self) -> AsyncOpenAI:
        if self._ollama is None:
            self._ollama = AsyncOpenAI(
                api_key="ollama",
                base_url=f"{settings.ollama_base_url}/v1",
            )
        return self._ollama

    def _get_provider_order(self, prefer_long_context: bool = False) -> list[tuple[str, str]]:
        if prefer_long_context:
            # Gemini primero para contextos largos (10-K completos)
            return [
                ("gemini", settings.gemini_model),
                ("groq", settings.groq_model),
                ("ollama", settings.ollama_model),
            ]

        primary = settings.primary_llm
        fallback = settings.fallback_llm

        order_map = {
            "groq": ("groq", settings.groq_model),
            "gemini": ("gemini", settings.gemini_model),
            "ollama": ("ollama", settings.ollama_model),
        }

        providers = [order_map[primary]]
        for name, pair in order_map.items():
            if name != primary and name != fallback:
                providers.append(pair)
        providers.append(order_map.get(fallback, ("ollama", settings.ollama_model)))
        return providers

    async def complete(
        self,
        messages: list[dict],
        response_schema: Type[T],
        prefer_long_context: bool = False,
    ) -> T:
        providers = self._get_provider_order(prefer_long_context)

        for provider, model in providers:
            attempt_messages = messages
            for attempt in range(2):
                try:
                    result = await self._call(provider, model, attempt_messages, response_schema)
                    self.last_provider = provider
                    self.last_model = model
                    logger.info("LLM call succeeded", provider=provider, model=model)
                    return result
                except ProviderExhausted:
                    logger.debug("Provider quota exhausted (cached), skipping", provider=provider, model=model)
                    break  # pasar al siguiente proveedor sin reintentar
                except RateLimitError:
                    logger.warning("Rate limit hit", provider=provider, model=model)
                    break  # pasar al siguiente proveedor
                except (ValueError, json.JSONDecodeError) as e:
                    logger.warning("JSON parse failed", provider=provider, attempt=attempt, error=str(e))
                    if attempt == 1:
                        break  # pasar al siguiente proveedor tras 2 intentos
                    # Feed the validation error back so the retry can actually
                    # self-correct instead of repeating the same mistake —
                    # without this, attempt 2 is an identical prompt and (at
                    # temperature 0.1) tends to reproduce the same bad output.
                    attempt_messages = messages + [{
                        "role": "user",
                        "content": (
                            "Tu respuesta anterior no fue válida — falló esta validación:\n"
                            f"{e}\n\n"
                            "Corrígela y responde de nuevo con un JSON que cumpla EXACTAMENTE "
                            "el schema (tipos y rangos de cada campo)."
                        ),
                    }]
                except Exception as e:
                    logger.error("LLM call failed", provider=provider, model=model, error=str(e))
                    break

        raise AllProvidersExhausted("All LLM providers failed")

    async def _call(self, provider: str, model: str, messages: list[dict], schema: Type[T]) -> T:
        from app.data.rate_limiter import get_rate_limiter
        rl = get_rate_limiter()
        key = _rate_limit_key(provider, model)

        if await rl.is_exhausted(key):
            raise ProviderExhausted(f"{provider} quota exhausted for today, skipping")

        await rl.acquire(key)

        if provider == "groq":
            return await self._call_openai_compatible(self.groq, model, messages, schema, strict=False)
        elif provider == "ollama":
            return await self._call_openai_compatible(self.ollama, model, messages, schema, strict=False)
        elif provider == "gemini":
            return await self._call_gemini(model, messages, schema)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def _call_openai_compatible(
        self,
        client: AsyncOpenAI,
        model: str,
        messages: list[dict],
        schema: Type[T],
        strict: bool = True,
    ) -> T:
        json_schema = schema.model_json_schema()

        if strict:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema,
                    "strict": True,
                },
            }
            call_messages = messages
        else:
            response_format = {"type": "json_object"}
            # Inject schema into last user message so model knows expected structure.
            # Weaker models (small local Ollama models) sometimes echo the schema
            # definition itself back as the "answer" — be explicit that this is a
            # schema to fill in, not the response, to reduce that failure mode.
            call_messages = list(messages)
            for i in range(len(call_messages) - 1, -1, -1):
                if call_messages[i]["role"] == "user":
                    call_messages[i] = dict(call_messages[i])
                    call_messages[i]["content"] += (
                        f"\n\nResponde ÚNICAMENTE con un objeto JSON que contenga VALORES REALES "
                        f"para cada campo (no el schema, no placeholders).\n"
                        f"El siguiente es el JSON SCHEMA que describe la ESTRUCTURA esperada "
                        f"(nombres de campo y tipos) — tu respuesta debe ser una INSTANCIA de "
                        f"datos que valide contra este schema, nunca el schema en sí:\n"
                        f"{json.dumps(json_schema, indent=2)}"
                    )
                    break

        resp = await client.chat.completions.create(
            model=model,
            messages=call_messages,
            response_format=response_format,
            temperature=0.1,
        )

        content = resp.choices[0].message.content or ""
        content = _strip_think_tags(content)
        content = _extract_json(content)
        data = json.loads(content)
        return schema.model_validate(data)

    async def _call_gemini(self, model: str, messages: list[dict], schema: Type[T]) -> T:
        from google import genai
        from google.genai.types import GenerateContentConfig

        if self._gemini is None:
            self._gemini = genai.Client(api_key=settings.google_api_key)

        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        user_parts = [m["content"] for m in messages if m["role"] == "user"]
        system_instruction = "\n\n".join(system_parts) if system_parts else None

        user_prompt = "\n\n".join(user_parts)
        user_prompt += f"\n\nResponde ÚNICAMENTE con JSON válido según este schema:\n{json.dumps(schema.model_json_schema(), indent=2)}"

        gemini_client = self._gemini
        loop = asyncio.get_event_loop()

        def _call():
            resp = gemini_client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            return resp.text

        for attempt in range(2):
            try:
                text = await loop.run_in_executor(None, _call)
                text = _strip_think_tags(text)
                text = _extract_json(text)
                data = json.loads(text)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Gemini JSON parse failed", attempt=attempt, error=str(e))
                if attempt == 1:
                    raise
            except Exception as e:
                err_str = str(e)
                if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str:
                    # Google's retryDelay hint (seconds) is meant for short per-minute
                    # bursts. The free tier's binding constraint here is normally the
                    # *daily* request cap ("PerDay" in the quotaId), which won't
                    # actually reset on that short timer — so once we see this,
                    # assume it's the daily cap and skip Gemini until UTC midnight
                    # rather than hammering it again in a few seconds.
                    from app.data.rate_limiter import get_rate_limiter
                    await get_rate_limiter().mark_exhausted("gemini_flash")
                logger.error("Gemini call failed", model=model, error=err_str)
                raise

        raise ValueError("Gemini: all attempts failed")


def _rate_limit_key(provider: str, model: str) -> str:
    if provider == "groq":
        return "groq_llama8b" if "8b" in model else "groq_llama70b"
    if provider == "gemini":
        return "gemini_flash"
    return provider


def _strip_think_tags(text: str) -> str:
    """Elimina bloques <think>...</think> de DeepSeek-R1."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json(text: str) -> str:
    """Extrae JSON de texto que puede tener markdown fences."""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    # Buscar JSON sin fences
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return text


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
