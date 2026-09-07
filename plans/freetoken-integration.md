# Evaluar FreeToken como reemplazo del stack LLM (Groq + Gemini + Ollama)

## Contexto

El bot depende hoy de Groq (Llama 3.3 70B, primario) y Gemini Flash (contexto largo para 10-Ks), con Ollama local como fallback. Groq/Gemini son APIs cloud con free tier limitado (rate limits diarios/por minuto) y el usuario quiere reducir esa dependencia. Salió a la luz **FreeToken** (github.com/FlashML-org/FreeToken, paper arXiv:2608.16157, ago. 2026 — equipo con Song Han, Kurt Keutzer, Ion Stoica, Matei Zaharia), un motor de inferencia que sirve modelos MoE grandes (ej. Qwen3.6-35B-A3B, hasta 753B en hardware workstation) en GPUs de consumo, tratando VRAM+RAM+disco como una jerarquía de memoria elástica. Reclama 3-4x más rápido que Ollama en decode para MoE.

**Restricción encontrada en la investigación:** FreeToken solo soporta **Linux x86_64 + GPU NVIDIA (driver r580+/CUDA 13)** — sin Windows nativo, sin macOS, sin imagen Docker oficial. La primera versión de este plan asumía correrlo vía WSL2 (no validado oficialmente por FreeToken), pero el usuario aclaró que su PC es **dual-boot con Ubuntu nativo instalado**, lo cual elimina ese riesgo por completo: FreeToken corre en su modo soportado oficialmente, sin virtualización ni passthrough de GPU de por medio.

**Hardware verificado en esta sesión** (`nvidia-smi`/`wmic`, desde el lado Windows — la GPU física es la misma al bootear a Ubuntu):
- GPU: RTX 4070 Ti SUPER, 16 GB VRAM, driver 591.86, CUDA 13.1 en Windows (cumple el requisito de FreeToken; en Ubuntu habrá que confirmar que el driver NVIDIA instalado ahí también sea r580+/CUDA 13 — puede ser una versión de driver distinta a la de Windows).
- RAM: ~32 GB (compartida entre ambos SO, no duplicada).

Dado 32 GB de RAM, el nivel de modelo realista es la clase **~35B MoE** (Qwen3.6-35B-A3B), no los niveles 284B/753B que requieren mucha más RAM para el offload.

El usuario confirmó: quiere evaluarlo como **posible reemplazo de todo el stack** (no solo del fallback Ollama). Dado que quedan dos incertidumbres reales (¿la calidad de un modelo ~35B local iguala a Groq 70B/Gemini Flash en las tareas de JSON estructurado del bot?, ¿vale la pena el costo de tener la GPU encendida vs APIs cloud gratuitas?), el enfoque sigue siendo un **spike por etapas con gates**, no un swap de una sola vez.

**Flujo de trabajo acordado:** el spike se ejecuta al bootear a Ubuntu, retomando desde la Etapa 1 de este documento.

## Arquitectura actual (verificado en código)

`stock-bot/app/llm/client.py` — `LLMClient` es la única abstracción de proveedor:
- `_get_provider_order()` (líneas 59-82) arma la cadena de fallback desde `settings.primary_llm`/`fallback_llm`.
- `complete()` (84-128): recorre proveedores, 2 reintentos c/u, cae al siguiente ante `ProviderExhausted`/`RateLimitError`/error de validación JSON.
- `_call()` (130-151): despacha a `_call_openai_compatible` (hoy usado por `groq` y `ollama`, ambos hablan la API OpenAI-compatible) o `_call_gemini` (SDK `google-genai` directo).
- `ollama` property (50-57): `AsyncOpenAI(api_key="ollama", base_url=f"{settings.ollama_base_url}/v1")` — Ollama se consume puramente vía su endpoint OpenAI-compatible, sin SDK especial.
- `_call_openai_compatible` (153-204): para proveedores no-strict (Ollama hoy) usa `response_format={"type":"json_object"}` + inyección manual del schema en el prompt + `_strip_think_tags`/`_extract_json` para sacar el JSON del texto crudo.
- `stock-bot/app/config.py:14-16` — `Literal["groq","gemini","ollama","openrouter"]` para `primary_llm`/`fallback_llm`/`long_context_llm`. `openrouter` es config muerta (nunca se llama en `_call()`), se deja intacta, no es parte de este trabajo.
- `.env` real: `PRIMARY_LLM=groq`, `FALLBACK_LLM=ollama`, `LONG_CONTEXT_LLM=gemini`.

**FreeToken no tiene salida estructurada / json_schema documentada** en su endpoint — se comporta igual que Ollama hoy (modo no-estricto), así que la integración reutiliza exactamente el mismo camino de código, sin capacidad nueva que añadir al cliente.

## Plan por etapas (para ejecutar en Ubuntu)

### Etapa 1 — Spike de entorno nativo (gate pasa/no-pasa antes de tocar código)

Objetivo: probar que FreeToken puede servir Qwen3.6-35B-A3B nativamente en Ubuntu.

1. Confirmar driver NVIDIA en Ubuntu: `nvidia-smi` debe reportar driver r580+ y CUDA 13.x. Si el driver instalado en Ubuntu es más viejo, actualizarlo primero (`ubuntu-drivers` o el repo de NVIDIA) — no asumir que coincide con el driver de Windows, son instalaciones independientes.
2. Confirmar CUDA toolkit/`nvcc` instalado (FreeToken compila kernels JIT en el primer uso).
3. Instalar FreeToken (`uv pip install "freetoken[accel]"`) en un venv dedicado.
4. Servir el modelo: `ft serve --model Qwen3.6-35B-A3B` con `--memory-ratio` y `--moe-backend hybrid`/`--moe-cpu-layers` ajustados al presupuesto de 16GB VRAM/32GB RAM (dejar margen para el resto del sistema). Esperar el log "API server is ready to serve on 127.0.0.1:1919".
5. Probar localmente: `curl http://127.0.0.1:1919/v1/models` y una llamada trivial a `/v1/chat/completions` — todo en la misma máquina/SO, sin networking cruzado que resolver (a diferencia del enfoque WSL2 original).
6. Registrar: tiempo de carga, latencia al primer token, tokens/seg en decode, uso de VRAM/RAM durante una request (`nvidia-smi`, `free -h`).

**Gate para pasar a Etapa 2:** el modelo carga sin OOM, y una respuesta básica es coherente. Si algo falla y no es arreglable en ~1 día de esfuerzo, documentar la causa (OOM, driver/CUDA, errores de compilación JIT) antes de seguir.

### Etapa 2 — Integración de código (reutilizar la abstracción existente)

Solo si Etapa 1 pasa. FreeToken se trata exactamente como Ollama hoy — mismo camino no-estricto, sin código nuevo bespoke. Dado que en Ubuntu se puede correr el stack completo (FastAPI + FreeToken) en la misma máquina, no hace falta ninguna configuración especial de red — todo es `localhost`.

- **`stock-bot/app/config.py`**: agregar `"freetoken"` al `Literal` de `primary_llm`/`fallback_llm`/`long_context_llm`; agregar `freetoken_base_url: str = "http://localhost:1919"` y `freetoken_model: str = "Qwen3.6-35B-A3B"`.
- **`stock-bot/app/llm/client.py`**:
  - Agregar property `freetoken` (cacheada) igual que `ollama`: `AsyncOpenAI(api_key="freetoken", base_url=f"{settings.freetoken_base_url}/v1")`.
  - En `order_map` (dentro de `_get_provider_order()`): agregar `"freetoken": ("freetoken", settings.freetoken_model)`.
  - En `_call()`: agregar `elif provider == "freetoken": return await self._call_openai_compatible(self.freetoken, model, messages, schema, strict=False)`.
  - No tocar el branch `prefer_long_context` en Etapa 2 (Gemini sigue cubriendo mejor los 10-Ks completos; revisar en Etapa 4 solo si el benchmark lo justifica).
  - No tocar la lógica de reintentos/excepciones de `complete()` — ya trata a todo proveedor de forma uniforme vía `_call()`.
  - Actualizar el docstring de `LLMClient` (línea 30) para reflejar que la cadena es configurable vía `.env`, no fija en el código.
- **`stock-bot/app/data/rate_limiter.py`**: opcionalmente agregar `"freetoken": {"rpm": None, "rpd": None}` a `RATE_LIMITS` por consistencia con la entrada `"ollama"` (línea 20) — no es funcionalmente necesario, ya que un proveedor sin entrada cae a `{}` (sin límite), que es el comportamiento correcto para un recurso local.
- **`stock-bot/.env.example`**: agregar `FREETOKEN_BASE_URL=http://localhost:1919` y `FREETOKEN_MODEL=Qwen3.6-35B-A3B` cerca de las líneas de `OLLAMA_*`. No cambiar los defaults de `PRIMARY_LLM`/`FALLBACK_LLM`/`LONG_CONTEXT_LLM` — Etapa 2 solo habilita el valor, no lo activa.
- **`stock-bot/SETUP.md`**: documentar FreeToken como alternativa local experimental (Linux nativo, GPU NVIDIA requerida).
- **`stock-bot/docker-compose.yml`** y **`requirements.txt`**: sin cambios — FreeToken se consume como servicio HTTP vía el SDK `openai` ya existente, y no se conteneriza por ahora (sin imagen oficial, requiere compilación JIT CUDA que no encaja bien en un container sin spike aparte).

### Etapa 3 — Harness de benchmark (reutilizar los agentes existentes)

Comparar FreeToken vs Groq vs Gemini vs Ollama usando los prompts reales de la app, sin construir un framework de evaluación aparte:

1. Elegir 3-5 tickers reales ya conocidos por funcionar con el pipeline actual (revisar `stock-bot/tests/` o historial del dashboard).
2. Para cada uno de los 6 módulos de agente (`fundamental_agent.py`, `technical_agent.py`, `sentiment_agent.py`, `macro_agent.py`, `peer_agent.py`, `aggregator_agent.py`), invocar `run_*_agent(state)` con el mismo `state` fijo por ticker, variando `primary_llm`/`fallback_llm` **al mismo proveedor** (para forzar una señal de un solo proveedor real, en vez de que el fallback enmascare fallos).
3. Registrar por (ticker, agente, proveedor): éxito/fallo (`AllProvidersExhausted` o no), latencia, y el objeto Pydantic validado para revisión manual. Guardar en un CSV fuera del repo (scratch, no commitear).
4. Revisión de calidad subjetiva: leer lado a lado 2-3 tickers por agente (Groq vs FreeToken), buscando números alucinados, respuestas técnicamente válidas pero vacías/genéricas (falla típica de modelos más débiles en modo no-estricto), y veredictos que difieran mucho del baseline cloud.
5. Correr un `graph.ainvoke()` completo (vía `build_workflow()`) con `PRIMARY_LLM=freetoken` para al menos un ticker, confirmando que el pipeline completo (los 6 agentes + aggregator) termina sin `AllProvidersExhausted`.

**Nota de latencia:** la compilación JIT de kernels CUDA de FreeToken ocurre una sola vez al iniciar el servidor, no por request — calentar el servidor antes de medir latencia para no sesgar el benchmark.

### Etapa 4 — Decisión de rollout (solo config, gated por datos de Etapa 3)

Sin cambios de código — solo valores en `.env`, ya que `_get_provider_order()` ya soporta cualquier orden:

- **FreeToken como primario** (`PRIMARY_LLM=freetoken`) si: tasa de validación comparable a Groq en los 6 agentes, latencia aceptable para la cadencia real del bot (es mensual según `PRODUCT.md`/`SETUP.md`, no interactivo de baja latencia — revisar `ANALYSIS_FLOW.md` para confirmar cadencia real antes de tratar la latencia como bloqueante duro), y sin degradación sistemática de calidad.
- **FreeToken solo como fallback adicional/mejorado** (reemplazando a Ollama en ese rol, con Groq de primario) si la calidad es decente pero claramente por debajo de Groq.
- **Descartar FreeToken** si Etapa 1 falla, o si Etapa 3 muestra calidad/validación peor que el Ollama actual, o si el costo de tener la GPU encendida continuamente no se justifica frente a los free tiers de Groq/Gemini para un bot de cadencia mensual. Nota: al usar dual-boot, "tener la GPU encendida" implica estar booteado en Ubuntu en vez de Windows durante la corrida mensual del bot — considerar si eso es operativamente cómodo o una fricción real.
- En todos los casos: no remover las dependencias/código de `groq`/`google-genai`/`ollama` — el diseño sigue siendo multi-proveedor con fallback, no un reemplazo de la abstracción.

## Riesgos y supuestos a llevar explícitamente

- El driver NVIDIA en la partición Ubuntu puede no estar en la misma versión que en Windows — verificar r580+/CUDA 13 ahí específicamente en la Etapa 1, no asumir por los datos de Windows.
- Sin salida estructurada garantizada en FreeToken — paridad con la limitación actual de Ollama, no mejora en ese eje.
- 32GB RAM limita el nivel de modelo a la clase ~35B; los niveles 284B/753B quedan fuera de alcance con este hardware.
- Dual-boot implica que correr el bot con FreeToken requiere estar booteado en Ubuntu — si la cadencia mensual del bot necesita correr automáticamente desde Windows (scheduler/APScheduler), esto es una fricción operativa a resolver en la Etapa 4, no solo un tema de calidad de modelo.

## Verificación end-to-end (después de que el código de Etapa 2 esté listo, en Ubuntu)

1. **Chequeo HTTP crudo**: `curl http://127.0.0.1:1919/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"Qwen3.6-35B-A3B","messages":[{"role":"user","content":"Reply with the single word OK"}]}'` — confirma que el servidor FreeToken responde.
2. **Llamada manual a `LLMClient.complete()`**: script ad-hoc (no commiteado) con `primary_llm="freetoken"`, `fallback_llm="freetoken"`, llamando `await get_llm_client().complete(messages, FundamentalAnalysis)` con un prompt real de `fundamental_agent.py` — confirma que `_call_openai_compatible`, la inyección de schema y `_extract_json`/`_strip_think_tags` funcionan contra el formato de salida real de FreeToken.
3. **Corrida completa del pipeline**: con `PRIMARY_LLM=freetoken` en `.env`, disparar `build_workflow().ainvoke(...)` para un ticker real — confirma que los 6 agentes + aggregator completan sin `AllProvidersExhausted` y que `save_suggestion` produce un registro final coherente.
4. Solo después de que estos 3 smoke tests pasen, correr el barrido completo de benchmark de la Etapa 3.

## Archivos críticos

- `stock-bot/app/config.py`
- `stock-bot/app/llm/client.py`
- `stock-bot/app/data/rate_limiter.py`
- `stock-bot/.env.example`
- `stock-bot/SETUP.md`
