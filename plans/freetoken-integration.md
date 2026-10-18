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

### Etapa 4 — Decisión de rollout (EJECUTADA 2026-09-13)

**Corrección de cadencia respecto al plan original**: `PRODUCT.md` no existe en el repo, y tanto `SETUP.md` ("Sistema de sugerencias de inversión mensual") como el plan original asumían cadencia **mensual**. El código real (`app/scheduler.py::weekly_analysis_job`, cron `day_of_week="sun", hour=23`) y el propio `SETUP.md` línea 359 ("Con 13 tickers en el watchlist y análisis semanal...") confirman que la cadencia real es **semanal**, no mensual — corriendo los 13 tickers del watchlist en un `for` secuencial, uno detrás del otro (no en paralelo entre tickers).

**Cálculo de latencia real** (con el dato empírico de la Etapa 3 punto 5: 1392s/ticker con FreeToken, incluyendo mala suerte con 2 ciclos de timeout+reintento): 13 tickers × ~23 min ≈ **~5 horas** de corrida semanal completa, arrancando el domingo 23:00 UTC. Eso implica la máquina booteada en Ubuntu (no Windows) esas ~5 horas cada domingo por la noche.

**Decisión del usuario, con el cálculo de arriba sobre la mesa**: 5 horas es aceptable — cae dentro de la ventana nocturna entre cierre y apertura de mercado (~10 horas), así que la latencia no se trata como bloqueante duro, tal como preveía el criterio original del plan ("revisar cadencia real antes de tratar la latencia como bloqueante duro").

**Gap de evidencia reconocido explícitamente**: en ningún momento de esta investigación (Etapas 1-3) hubo una `GROQ_API_KEY` real configurada — nunca se corrió el benchmark de la Etapa 3 en modo comparación cabeza a cabeza contra Groq (mismos tickers, mismo schema, proveedor real). La decisión de abajo se toma **sin** la confirmación de "tasa de validación comparable a Groq" que pedía el criterio original del plan — es un riesgo aceptado conscientemente, no una casilla marcada con datos.

### Configuración aplicada

```
PRIMARY_LLM=freetoken
FALLBACK_LLM=freetoken
LONG_CONTEXT_LLM=gemini   # sin cambios — no se validó FreeToken específicamente para 10-Ks largos
```

**`FALLBACK_LLM=freetoken` (no `ollama`, el default original) es deliberado**, no un descuido: es exactamente el comportamiento que salvó la corrida completa en la Etapa 3 punto 5 — cuando `technical_agent`/`macro_agent` agotaron el timeout del cliente contra FreeToken, `_get_provider_order()` (con `primary=fallback=freetoken`) arma la cadena `[freetoken, groq, gemini, ollama, freetoken]`, así que tras fallar en groq/gemini/ollama (sin configurar) la cadena vuelve a intentar FreeToken una segunda vez — y esa segunda vez funcionó las 2 veces que se necesitó. Si `FALLBACK_LLM` fuera `ollama` (sin servidor Ollama corriendo, como es el caso real de esta máquina), ese mismo timeout habría sido un fallo duro (`AllProvidersExhausted`) para el ticker en vez de recuperarse solo.

**Cambio de código acompañante** (`app/llm/client.py`, property `freetoken`): se subió el timeout del cliente HTTP de **180s → 600s**. Motivo: el timeout de 180s (agregado en la Etapa 1/2 de esta misma sesión como mitigación a los cuelgues de builds viejas de FreeToken) resultó demasiado corto bajo carga concurrente real — se midieron generaciones individuales de 5,000-9,000+ tokens de razonamiento (~150-220s de puro decode a ~41 tok/s) antes de la respuesta JSON visible, más el tiempo de cola detrás de otras requests concurrentes (FreeToken serializa la generación internamente pese a aceptar conexiones concurrentes — ver hallazgo de la Etapa 3 punto 5). 600s da margen real para una sola llamada larga bajo cola, sin ser un timeout "infinito" que reintroduzca el riesgo de cuelgue real que motivó el timeout en primer lugar.

**No se tocó nada de `groq`/`google-genai`/`ollama`** — el código y las dependencias de esos proveedores siguen intactos, el diseño sigue siendo multi-proveedor con fallback real disponible si en el futuro se decide revertir esta decisión (alcanza con cambiar `PRIMARY_LLM`/`FALLBACK_LLM` en `.env`, sin tocar código).

### Seguimiento recomendado, no ejecutado en esta sesión

- Si en algún momento se consigue una `GROQ_API_KEY`, vale la pena cerrar el gap de evidencia corriendo el mismo benchmark de la Etapa 3 en modo comparación real, para confirmar (o refutar) que la calidad de FreeToken es comparable — la decisión actual descansa en que la salida es técnicamente válida y coherente, no en una comparación de calidad directa.
- Monitorear las primeras 2-3 corridas semanales reales (domingo 23:00 UTC) para confirmar que el timeout de 600s es suficiente en producción y que el patrón de "reintento gratis vía FreeToken-como-su-propio-fallback" sigue siendo confiable bajo la carga real de 13 tickers (más variabilidad que el único ticker de prueba de la Etapa 3).
- Si la corrida semanal empieza a exceder cómodamente la ventana de 10 horas (por ejemplo, si crece el watchlist), reconsiderar paralelizar el `for` de `weekly_analysis_job` entre tickers — hoy es estrictamente secuencial.

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

## Resultados de la Etapa 1 (ejecutada 2026-09-07, Ubuntu 24.04.4)

**Gate: PASA.** El modelo carga sin OOM y una respuesta básica es coherente.

### Entorno preparado
- Driver NVIDIA 595.84 / CUDA 13.2 ya estaba listo (no requirió actualización).
- CUDA 13.2 toolkit instalado vía repo oficial de NVIDIA (`cuda-keyring` + `cuda-toolkit-13-2`, elegido para matchear la versión exacta que reporta el driver en vez del meta-paquete genérico que trae 13.3). `nvcc` agregado al `PATH` en `~/.bashrc`.
- `uv 0.12.10` instalado en `~/.local/bin` (sin sudo).
- `freetoken[accel]` 0.1.2 instalado en un venv dedicado (`~/freetoken-spike/.venv`), no en el venv del proyecto stock-bot.
- Modelo usado: **`nvidia/Qwen3.6-35B-A3B-NVFP4`** (cuantización 4-bit, ~22GB en disco) — elegida sobre FP8/BF16 por presupuesto de VRAM/RAM/disco más seguro para este primer spike.

### Bug encontrado en el downloader de FreeToken (workaround aplicado)
`ft serve --model nvidia/Qwen3.6-35B-A3B-NVFP4` descargó los 3 shards `.safetensors` pero **no bajó `model.safetensors.index.json` ni `hf_quant_config.json`**, que sí existen en el repo de HF. Sin el índice, la carga de "expert banks" NVFP4 falla con `FileNotFoundError`. Workaround: descargar esos 2 archivos manualmente al mismo cache con `huggingface_hub.hf_hub_download()` (mismo `snapshots/<hash>/` que ya pobló `ft serve`), sin necesidad de re-descargar los pesos. **Relevante para Etapa 2**: si se automatiza la descarga/arranque, hay que replicar este paso o esperar un fix upstream — no asumir que `ft serve --model <repo>` es suficiente solo, al menos para este checkpoint NVFP4 de NVIDIA.

### Métricas
- Arranque (proceso → "API server is ready to serve"), con archivos ya en cache: **~1m16s** (carga de pesos + expert banks NVFP4 ~21s + compilación JIT de kernels CUDA + captура de CUDA graphs ~46s).
- VRAM en reposo tras cargar: **~14.9-15GB / 16GB** — ajustado pero estable, sin OOM.
- RAM durante la construcción "serial" de expert banks (fallback automático por "low free RAM"): picos hasta ~26GB usados / 31GB, con el swap de 2GB casi lleno momentáneamente — se recuperó solo, no hubo OOM-kill del proceso (falso positivo inicial: se sospechó OOM-kill del kernel, descartado revisando `dmesg`/`journalctl`, el proceso seguía vivo compilando kernels).
- Primer request de inferencia: **~50s** (compilación JIT lazy de kernels adicionales en el primer forward real — coincide con la nota del plan de que esto es un costo único, no por-request).
- Requests siguientes ("en caliente"): **~46-75 tokens/seg en decode**, latencia total de 2-4s para respuestas de ~150-200 tokens.
- Respuesta de smoke test ("Reply with the single word OK") → contenido final `"OK"`, `finish_reason: "stop"` — coherente y correcta.

### Hallazgo nuevo, no cubierto en el plan original: modelo de razonamiento ("thinking")
Qwen3.6-35B-A3B-NVFP4 emite un bloque de **`reasoning_content` (cadena de pensamiento oculta) antes del `content` final**, similar a otros modelos "thinking" de la familia Qwen3. Con `max_tokens=16` o `max_tokens=200` el modelo agotó el presupuesto completo *dentro* del razonamiento y devolvió `content:""` con `finish_reason:"length"` — recién con `max_tokens=600` llegó a la respuesta final tras ~150-190 tokens de razonamiento.

**Implicación directa para la Etapa 2/3**: los agentes del bot (`fundamental_agent.py`, etc.) esperan JSON estructurado como salida final. Si FreeToken enruta el razonamiento a `reasoning_content` y el JSON esperado queda en `content`, el pipeline actual (`_extract_json`/`_strip_think_tags` en `client.py`) debería funcionar bien siempre que el `content` final llegue completo — pero **`max_output_tokens` debe ser considerablemente más alto** que con Groq/Gemini (que no razonan de la misma forma) para no cortar la respuesta a mitad de camino. Esto hay que validarlo explícitamente en el benchmark de la Etapa 3, revisando `finish_reason` por cada llamada (si aparece `"length"` en vez de `"stop"`, la respuesta probablemente esté incompleta/inválida).

## Resultados de la Etapa 2 (ejecutada 2026-09-07): código integrado, pero BLOQUEADO por bug de FreeToken

**Código:** Se implementó exactamente lo descrito en la sección "Etapa 2" de arriba — `freetoken` agregado como proveedor válido en `config.py` (Literal + `freetoken_base_url`/`freetoken_model`, default `Qwen3.6-35B-A3B-NVFP4`), `client.py` (property `freetoken`, entrada en `order_map`, branch en `_call()`, docstring actualizado), `rate_limiter.py` (entrada sin límite), `.env.example` y `SETUP.md` documentados. Compila sin errores (`python3 -m py_compile`). Los defaults de `PRIMARY_LLM`/`FALLBACK_LLM`/`LONG_CONTEXT_LLM` NO cambiaron — FreeToken queda disponible pero inactivo por defecto, tal como especificaba el plan.

**Verificación end-to-end: FALLA.** Al probar `_call_openai_compatible` contra el servidor real con el patrón exacto que usa el bot (inyección del JSON schema de un modelo Pydantic real, `FundamentalAnalysis`, en el último mensaje `user`), se encontraron dos problemas, uno bloqueante:

1. **`response_format={"type":"json_object"}` no soportado — RESUELTO en el código.** FreeToken devolvía `400 Bad Request: "response_format json_object/json_schema is not supported (no constrained decoding)"`. Se agregó el parámetro `send_response_format` a `_call_openai_compatible` (default `True`, sin cambio de comportamiento para groq/ollama) y el branch de `freetoken` en `_call()` lo pasa en `False` — ya no manda ese campo. También se agregó `timeout=180.0` al cliente `AsyncOpenAI` de `freetoken` (property en `client.py`) como mitigación defensiva del punto 2 de abajo: sin esto, un cuelgue del servidor bloquearía `complete()` para siempre; con el timeout, `openai.APITimeoutError` cae en el `except Exception` genérico de `complete()` y pasa al siguiente proveedor del fallback chain tras ~180s por intento.

2. **BLOQUEANTE — cuelgue indefinido con prompts que contienen un JSON schema embebido.** Quitar `response_format` no alcanza: cualquier request cuyo prompt incluya el JSON schema completo de Pydantic (`schema.model_json_schema()`, el mecanismo que `_call_openai_compatible` usa para *todo* proveedor no-strict, incluido Ollama hoy) hace que el servidor **nunca responda ni falle** — ni error, ni timeout del lado del servidor, simplemente no vuelve a loguear nada después de recibir la conexión. El proceso queda con la GPU al 100% indefinidamente (se confirmó >2h en un caso, y >30min de espera del lado del cliente en otro, sin señales de progreso). Reproducido en 3 arranques limpios distintos del servidor.

   **Aislado con precisión** mediante pruebas A/B/C/D controladas:
   - Prompt corto + `max_tokens=2000` → funciona bien (2-4s, `finish_reason:"stop"`).
   - Prompt largo con JSON schema embebido + `max_tokens=50` (chico) → **se cuelga igual**. No es cuestión de presupuesto de tokens de salida.
   - Prompt del mismo largo en caracteres pero SIN el JSON schema (texto de relleno tipo lorem ipsum) + `max_tokens=50` → funciona bien, responde normal.
   - Mismo prompt con schema, probando `--tool-call-parser qwen` en vez del default `qwen3_coder` → **se cuelga igual** (descarta que sea específico del parser de tool-calls).
   - En el log del servidor **nunca aparece la línea "Prefill batch"** para estas requests colgadas — el cuelgue ocurre en el preprocesamiento de la request (tokenización/parsing), antes de que el scheduler la vea, no durante la generación de tokens.

   **Causa raíz: no confirmada.** El disparador es específicamente el *contenido* JSON-schema-shaped del prompt (llaves anidadas, `"type"`, `"properties"`, `"$defs"`, etc. — la salida de `pydantic.BaseModel.model_json_schema()`), independiente de `max_tokens` y del `tool_call_parser` configurado. No se investigó más a fondo (requeriría acceso al código fuente de FreeToken o reportarlo upstream).

   **Hallazgo operativo adicional, independiente del bug de arriba:** matar el proceso `ft serve` (`pkill`/`kill`) **no mata a sus hijos** (`multiprocessing.spawn`, el scheduler real que usa la GPU) — quedan huérfanos consumiendo GPU al 100% indefinidamente hasta matarlos manualmente por PID. Cualquier script de automatización/reinicio para Etapa 3+ necesita matar explícitamente el árbol de procesos, no solo el PID de `ft serve`.

   También se observó que el paso de arranque "capturar CUDA graphs" (`--cuda-graph-max-bs` por defecto) colgó indefinidamente una vez de tres arranques, sin ninguna request de por medio — posiblemente por el margen de VRAM libre muy ajustado (~1.2GB de 16GB) en ese punto. Arrancar con `--cuda-graph-max-bs 0` (desactiva la captura, acepta algo de latencia extra) evitó ese cuelgue específico en los reintentos posteriores.

### Impacto en el plan

El código de la Etapa 2 queda commiteable tal cual (no rompe nada, FreeToken sigue inactivo por defecto), pero **no se puede activar `PRIMARY_LLM=freetoken` ni `FALLBACK_LLM=freetoken` en la práctica** hasta resolver el cuelgue del punto 2 — el mecanismo de schema-injection es el único camino no-strict que usa `_call_openai_compatible`, y es exactamente el que dispara el bug. La Etapa 3 (benchmark) no puede arrancar mientras este bloqueante siga abierto.

### Intento de aislar el bug con otros modelos (no-Qwen)

Para descartar que el cuelgue sea específico de la arquitectura MoE/reasoning de Qwen3.6, se intentó reproducir el mismo test (prompt con JSON schema embebido) contra 3 checkpoints distintos, ninguno MoE:

| Modelo | Resultado |
|---|---|
| `AxionML/Gemma-4-12B-FP8` (denso, 12B) | **OOM** durante la carga de pesos (`torch.OutOfMemoryError`) — Gemma no tiene el offload automático a RAM que sí tiene el path MoE de Qwen, necesita entrar completo en 16GB y no entra (14GB+ solo de pesos, sin margen para el overhead de conversión de dtype durante la carga). |
| `AxionML/Gemma-4-12B-NVFP4` (denso, 12B) | **`RuntimeError: Unexpected keys in state_dict`** (`k_scale`/`v_scale` de todas las capas) — el checkpoint de este tercero no matchea el formato que espera el loader de FreeToken. Problema del checkpoint, no de FreeToken en sí. |
| `neuralmagic/Meta-Llama-3.1-8B-Instruct-FP8` (denso, 8B, fuente confiable) | **`IndexError: Dimension out of range`** en `freetoken/models/loader.py::shard_tensor` (`value.chunk(world_size, dim=1)` sobre un tensor que no tiene esa dimensión) — este sí es un bug de FreeToken mismo en el path de carga de pesos para modelos Llama, no del checkpoint. |

**Ningún modelo alternativo llegó siquiera a servir**, así que no se pudo confirmar ni descartar directamente si el cuelgue del schema-injection es específico de Qwen3.6 o generalizado — pero el patrón (3 modelos, 3 bugs de carga distintos, todos previos a poder testear una sola request) sugiere que **FreeToken 0.1.2 es frágil fuera del camino específico con el que fue validado** (el checkpoint oficial `nvidia/Qwen3.6-35B-A3B-NVFP4`, el único de los 4 probados en toda la sesión que cargó y sirvió sin problemas). Se decidió no seguir gastando tiempo/GPU probando más checkpoints — retornos decrecientes.

### Descartada la hipótesis de "margen de VRAM ajustado" como causa del cuelgue

El README de FreeToken reporta el mismo checkpoint (`nvidia/Qwen3.6-35B-A3B-NVFP4`) corriendo a 39.3 tok/s en una laptop con solo **8GB de VRAM** — mucho más ajustado que los 16GB de esta máquina. Esto motivó una prueba directa: relanzar el servidor con `--memory-ratio 0.5` (en vez del default 0.9) para forzar más offload a RAM y dejar mucho más margen de VRAM libre, y repetir el request que se cuelga.

- Con `--memory-ratio 0.9` (default): ~1.2GB libres tras inicializar → **cuelgue**.
- Con `--memory-ratio 0.5`: **7.2GB libres** tras inicializar (uso total ~8.5GB, replicando de hecho el escenario "GPU de 8GB" del README) → **el mismo prompt con schema JSON se cuelga exactamente igual** (GPU al 100%, sin log de "Prefill batch", sin respuesta).

**Conclusión:** el cuelgue es 100% independiente del margen de VRAM disponible — no es un problema de memoria ajustada ni un fluke de esta GPU/config particular. Es un bug de lógica/parsing en el preprocesamiento de la request, disparado puramente por el contenido JSON-schema-shaped del prompt, reproducible con total margen de memoria de sobra.

### Investigación de causa raíz

Se descartó primero, con pruebas directas fuera del servidor, que el cuelgue esté en la capa de texto:
- `tokenizer.apply_chat_template()` sobre el mensaje exacto que cuelga → **instantáneo** (0.013s), prompt renderizado normal (termina en `<|im_start|>assistant\n<think>`, forzando modo razonamiento — esperado).
- `tokenizer.encode()` sobre ese mismo prompt → **instantáneo** (0.0015s), 409 tokens, sin nada patológico.

Esto acota el bug al motor/scheduler de FreeToken (`kvcache/radix/` — el prefix-cache tipo radix-tree — o la coordinación CPU↔GPU del MoE), no a texto/tokenización.

**Se encontró el issue casi-idéntico en el repo oficial:** [`FlashML-org/FreeToken#259`](https://github.com/FlashML-org/FreeToken/issues/259) — mismo modelo (`Qwen3.6-35B-A3B-NVFP4`), mismo síntoma exacto (`--moe-backend offload` cuelga indefinidamente en `/v1/chat/completions`, 0 bytes de respuesta, servidor pasa el healthcheck normal), y el mismo hallazgo independiente de procesos huérfanos que sobreviven a matar `ft serve`. El reporte nota que la GPU queda al 100% de uso pero con solo 50-55W de consumo (vs. 100-140W en generación real) — **firma de un loop de espera/poll, no cómputo real** — y que el backend `--moe-backend hybrid` (en vez del `offload` que se auto-selecciona) funcionaba bien en su caso.

**Se probó el workaround sugerido (`--moe-backend hybrid`) — mejora parcial, no resuelve:** con `hybrid`, la request esta vez sí logró pasar el punto donde antes se colgaba (**apareció el log "Prefill batch, #new-token: 409"**, algo que nunca ocurría con `offload`/auto), pero el cuelgue reaparece un paso más adelante, en la fase de *decode*: GPU pineada al 100% con 65W de consumo (misma firma de spin-loop que describe el issue), y solo 1 de los 15 hilos del "CPU MoE executor" pineado activo al 100% — consistente con el mismo patrón de espera bloqueada, no con cómputo distribuido real entre los hilos reservados.

**Conclusión de causa raíz:** es un bug real y ya reportado en el proyecto (issue #259, abierto y sin fix documentado a la fecha), en la coordinación entre el backend GPU y el executor CPU del MoE bajo carga con requests reales — el workaround de cambiar de `offload` a `hybrid` reduce el problema (pasa de colgarse en prefill a colgarse en decode) pero no lo elimina en esta versión (0.1.2). También relevante, sin explorar en profundidad por falta de tiempo: [issue #172](https://github.com/FlashML-org/FreeToken/issues/172) describe que un prompt más largo que la ventana deslizante (SWA) deja al servidor no-responsivo en el path de re-prefill — nuestro prompt de 409 tokens con `swa_full_tokens_ratio=0.2` podría estar tocando ese mismo path; no se confirmó.

### Umbral exacto del disparador (bisección, validada por el usuario en su propia terminal)

El usuario probó primero un schema simplificado a mano (sin `description`/`title`/`maxItems`, solo `type`/`items`/`required`) y **funcionó** — señal de que no cualquier JSON-schema-shaped content dispara el bug. Se hizo una bisección agregando de a un elemento hasta reproducirlo:

| Prueba | Campos | Caracteres del schema en el prompt | Resultado |
|---|---|---|---|
| Schema simplificado del usuario (sin description/title/maxItems) | 4 | ~250 | ✅ Responde |
| + `description` en cada campo | 4 | ~400 | ✅ Responde |
| + `title` en cada campo | 4 | ~450 | ✅ Responde |
| + `maxItems`/`minimum`/`maximum` | 4 | **603** | ✅ Responde |
| Mismo set, 5 campos (agregando `earnings_quality`) | 5 | **784** | ❌ Cuelga |
| 6 campos | 6 | 932 | ❌ Cuelga |
| 8 campos armados a mano (sin `$defs`, replica el schema real de `FundamentalAnalysis`) | 8 | 1162 | ❌ Cuelga |
| Schema real generado por `Pydantic.model_json_schema()` (el que usa `client.py`) | 8 | 1244 | ❌ Cuelga |

**No es un keyword específico** (`description`, `title`, `maxItems`, `minimum`/`maximum` — probados individualmente, ninguno lo dispara solo) **ni un artefacto de Pydantic** (`$defs`, etc. — el schema de 8 campos armado a mano sin esos artefactos también cuelga). El umbral está entre **603 y 784 caracteres** de contenido JSON-schema-shaped en el prompt (equivalente a la transición de 4→5 campos en este schema particular).

### Confirmación en vivo con `py-spy dump` (attach a un proceso realmente colgado)

Se instaló `py-spy` en el venv y se adjuntó (`sudo py-spy dump --pid <worker>`) al proceso trabado en dos configuraciones distintas, capturando el traceback de Python exacto en el momento del cuelgue — esto reemplaza toda la especulación anterior por evidencia directa. **Resultado: hay al menos DOS bugs de cuelgue independientes**, y cuál se dispara depende del `--attention-backend`:

**1) Con `--attention-backend fi` (FlashInfer, el que se auto-selecciona por defecto):**
```
wrapper (<string>:3)
__call__ (cutlass/cutlass_dsl/tvm_ffi_provider.py:1065)   <- tvm_ffi.Function.__call__: lanza el kernel YA compilado
rmsnorm_cute (flashinfer/norm/kernels/rmsnorm.py:1334)
_rmsnorm_impl (flashinfer/norm/__init__.py:196)
...
_project (freetoken/models/qwen3_5_moe/attention.py:74)
```
Se descartó que sea una compilación JIT en curso (no hay proceso `nvcc`/`cicc` activo, y no existe ningún `.lock` de rmsnorm en `~/.cache/flashinfer` ni `~/.cache/tvm-ffi`) — `tvm_ffi.Function.__call__` en esa línea es el *lanzamiento* del kernel ya compilado, no su compilación. El kernel CUDA `rmsnorm_cute` (implementado en CUTLASS DSL) queda colgado ejecutándose en la GPU — consistente con un bug de sincronización de bajo nivel (ej. threads divergiendo en una barrera) específico de esta implementación, disparado por ciertas formas/tamaños de tensor. Coincide con el issue [#220](https://github.com/FlashML-org/FreeToken/issues/220) (mismo GPU exacto, RTX 4070 Ti Super/SM89, root cause también en la compilación/ejecución de kernels de FlashInfer) — es posible que ese fix no esté incluido en la build 0.1.2 publicada en PyPI.

**2) Con `--attention-backend triton`** (evita el kernel de FlashInfer de arriba, pero cuelga en otro lado — mismo request, mismo prompt):
```
_invalidate_prefill_buffer (freetoken/moe/offload_cache.py:557)   <- self.slot_for_id.view(-1)[old_ids[old_ids >= 0].long()] = -1
copy (freetoken/moe/offload_cache.py:603)
prefetch_prefill_layer (freetoken/moe/offload_cache.py:615)
_wait_prefill_overlap (freetoken/layers/moe.py:422)
```
Este sí es el código de doble-buffer de MoE que se había señalado como sospechoso antes de tener evidencia directa — una escritura indexada (scatter) sobre un tensor CUDA que nunca retorna. Mismo patrón: probablemente un bug de kernel dependiente de la forma/distribución de índices (qué tan diversos son los expert-IDs activados), no una condición de carrera a nivel Python.

**Ambos casos comparten la firma de "spin/hang" a nivel de GPU** (100% de utilización reportada por `nvidia-smi`, pero solo 65-70W de consumo — muy por debajo de los 100-140W de cómputo real observado en generaciones exitosas) — consistente con un warp/bloque de CUDA parado en una barrera de sincronización que nunca se libera, no con cómputo real en curso.

**Conclusión revisada:** no es un único bug puntual sino (al menos) dos fallas independientes a nivel de kernel CUDA en FreeToken 0.1.2/sus dependencias (FlashInfer y el código propio de offload de MoE), ambas disparadas por el mismo umbral de tamaño/complejidad de prompt, y ninguna resoluble cambiando de backend — cambiar de `fi` a `triton` solo cambia CUÁL de los dos bugs se dispara, no si se cuelga.

### Fix real verificado para el bug #2 (`offload_cache.py`)

`_invalidate_prefill_buffer` usa indexado booleano dinámico (`old_ids[old_ids >= 0]`), que en PyTorch fuerza una sincronización CPU↔GPU (el tamaño del resultado depende de los datos). Dentro del bloque `with torch.cuda.stream(self.prefill_copy_stream):` de `prefetch_prefill_layer`, esa sincronización queda esperando detrás de un `wait_event()` a un evento de liberación (`prefill_release_events[buffer_id]`) que en ciertas condiciones no llega a tiempo. Se reescribió con operaciones de tamaño fijo (sin indexado dinámico, `torch.where` + `.clamp(min=0)`) — funcionalmente equivalente, pero sin forzar esa sincronización:

```python
def _invalidate_prefill_buffer(self, buffer_id: int) -> None:
    slot_start = buffer_id * self.num_experts
    slot_end = slot_start + self.num_experts
    old_ids = self.id_of_slot[slot_start:slot_end]
    valid = old_ids >= 0
    safe_idx = old_ids.clamp(min=0).long()
    current = self.slot_for_id.view(-1)[safe_idx]
    self.slot_for_id.view(-1)[safe_idx] = torch.where(
        valid, torch.full_like(current, -1), current
    )
    old_ids.fill_(-1)
    self.usage[slot_start:slot_end].zero_()
```

**Verificado end-to-end**: con este fix aplicado (`--attention-backend triton`), la misma request que antes se colgaba en `_invalidate_prefill_buffer` ahora avanza más allá de ese punto — el cuelgue se mueve a un bug distinto, más adelante en el pipeline (ver abajo). Es decir, el fix resuelve genuinamente SU deadlock específico.

### Bug #3: `qwen3_5_moe/gdn.py` (tracking de estado GDN en escenarios de hybrid-radix cache)

Con el fix de arriba aplicado, la misma request avanza y se cuelga en un lugar nuevo, dentro del forward pass de la capa GDN (Gated DeltaNet, la parte tipo-mamba de la arquitectura híbrida de Qwen3.6). Se capturaron 2 `py-spy dump` en corridas distintas, en 2 líneas diferentes del mismo archivo:

```
_write_track_snapshot (freetoken/models/qwen3_5_moe/gdn.py:145)   # cv.index_copy_(0, fla.track_dst, conv_win...)
forward (freetoken/models/qwen3_5_moe/gdn.py:214)
```
```
_gate_params (freetoken/models/qwen3_5_moe/gdn.py:110)   # g = -self.A_log.exp() * F.softplus(a.float() + self.dt_bias)
forward (freetoken/models/qwen3_5_moe/gdn.py:198)
```

**Receta de reproducción exacta, aislada y 100% reproducible** (se descartó primero que baste con "prompt > 64 tokens" en una request aislada — un prompt de contenido único de 86 tokens, sin ningún prefijo compartido con requests previas, respondió sin problema). El disparador real es una secuencia de 2 requests:
1. Request A: cualquier prompt que quede cacheado (prefix cache / radix cache).
2. Request B: un prompt que **comparte el prefijo de A y lo extiende**, cruzando el límite de `CHUNK_SIZE = 64` tokens (`freetoken/kernel/fla/chunk.py`) dentro de la porción nueva/no-cacheada — dispara el path de "hybrid-radix tracking" en `freetoken/attention/linear.py::_build_track_metadata` (activo solo cuando `r.mamba_ping_pong is not None`, es decir, solo para requests que reusan estado de una prefix-cache-hit).

Confirmado en vivo: request A = el schema de 4 campos (funciona, 214 tokens), request B = el mismo prompt + 1 campo más (5 campos) → cuelgue inmediato y reproducible.

**Relevancia directa para el bot**: como los 6 agentes mandan prompts con estructura y system-prompt muy similares entre sí (mismo formato, schemas parecidos), el escenario "prefix-cache-hit + extensión" **no es un caso raro** — es el patrón normal de uso repetido del bot. Esto hace que el bug #3 sea tan bloqueante en la práctica como el #1 y el #2, no un edge-case improbable.

**No se pudo diagnosticar la causa exacta a nivel de kernel CUDA.** Se intentó `cuda-gdb -p <pid> -ex "info cuda kernels"` (con `sudo`, cuda-gdb y nsys ya vienen instalados junto con el CUDA toolkit) para inspeccionar el kernel de GPU exacto donde queda parado — **el propio `cuda-gdb` quedó sin responder** al intentar adjuntarse/inspeccionar el proceso colgado (el proceso objetivo permaneció en estado `R` — corriendo — nunca pasó a `T` — detenido — pese a los intentos de interrupción). Esto es en sí mismo un dato relevante: sugiere que el cuelgue es un estancamiento real a nivel de hardware/driver de la GPU, no solo una espera del lado de Python, y que ni siquiera el debugger de NVIDIA logra tomar control limpio del contexto CUDA en este estado.

**Próximos pasos posibles (no ejecutados en esta sesión):**
- **Comentar en el issue existente** [`FlashML-org/FreeToken#259`](https://github.com/FlashML-org/FreeToken/issues/259) (o abrir uno nuevo más específico, dado que ahora se sabe que hay 2 causas distintas) con: el umbral exacto de tamaño (603 vs 784 caracteres), y los dos `py-spy dump` completos — son la evidencia más accionable que se puede aportar a los mantenedores, apunta directo a las líneas de código.
- Revisar si hay una versión más nueva de `freetoken` (se instaló 0.1.2) que ya tenga esto resuelto — dado que se encontraron 3 bugs de carga distintos en modelos densos además de estos 2 de generación, vale la pena chequear el changelog antes de invertir más tiempo en esta versión.
- Probar `--moe-backend cpu` o `--moe-backend fused`, y combinaciones con `--attention-backend fa`/`trtllm` (las opciones no probadas) — de las 2 combinaciones probadas (`fi`+auto-offload, `triton`+auto-offload), ambas cuelgan por razones distintas; no se probó si alguna combinación evita ambos bugs a la vez.
- Investigar el issue #172 (SWA + prompt largo → servidor no-responsivo) como posible causa relacionada al primer bug (FlashInfer), dado que no se descartó.
- Si se retoma, quedarse en la familia de checkpoints oficiales/grandes (MoE) con la que FreeToken sí funcionó, en vez de checkpoints densos de terceros — es el único camino validado hasta ahora.

## ACTUALIZACIÓN 2026-09-13 (2ª parte): Etapa 3 ejecutada — benchmark de los 6 agentes reales, 17/18 exitosos

Con la nightly build validada (ver sección de abajo), se corrió la Etapa 3 completa tal como la describe el plan original: los 6 agentes reales del bot (`fundamental_agent`, `technical_agent`, `sentiment_agent`, `macro_agent`, `peer_agent`, `aggregator_agent`) invocados directamente contra el servidor FreeToken real, con `PRIMARY_LLM=FALLBACK_LLM=LONG_CONTEXT_LLM=freetoken` forzado en `.env` (sin fallback que pudiera enmascarar un fallo real), sobre 3 tickers (AAPL, TSLA, MSFT) con datos sintéticos pero plausibles y deliberadamente contrastantes (AAPL/MSFT con fundamentals positivos, TSLA con fundamentals negativos — revenue cayendo, earnings miss).

### Entorno del benchmark

- Venv nuevo del propio proyecto (`stock-bot/.venv`) con `requirements.txt` completo instalado (no reutiliza el venv de `freetoken-spike`).
- Redis levantado standalone vía Docker (`redis:7-alpine`, sin el resto de `docker-compose.yml` — no hizo falta Postgres, se usó SQLite) para satisfacer `init_rate_limiter()`, requisito real de `client.py` que no estaba cubierto en las pruebas curl directas de las secciones anteriores.
- `.env` real creado en la raíz del repo (antes solo existía `.env.example`) con las API keys de datos (Finnhub/FMP/etc.) vacías a propósito — el script de benchmark no pasa por `fetch_data_node`, arma el `state` de cada agente a mano, así que no necesita esas keys.
- Script de benchmark ad-hoc (no commiteado, vive en el scratchpad de la sesión) que reproduce el diseño descrito en el plan original: construye un `state` fijo por ticker, invoca cada `run_*_agent(state)` directamente, mide latencia y éxito/fallo, encadena las salidas reales de los 5 primeros agentes hacia el `state` del `aggregator_agent` (igual que haría `build_workflow()`), y vuelca todo a un CSV.

### Resultado: 17/18 llamadas de agente exitosas, CERO cuelgues

| Agente | AAPL | TSLA | MSFT | Latencia prom. |
|---|---|---|---|---|
| `fundamental_agent` | ✅ 59.5s (score 0.78) | ✅ 70.5s (score 0.38) | ✅ 69.5s (score 0.78) | ~66s |
| `technical_agent` | ✅ 86.0s (score 0.85) | ✅ 90.9s (score 0.35) | ✅ 86.5s (score 0.78) | ~88s |
| `sentiment_agent` | ✅ 49.3s (bullish) | ✅ 45.0s (bearish) | ✅ 49.6s (bullish) | ~48s |
| `macro_agent` | ✅ 49.1s (score 0.75) | ✅ 51.8s (score 0.75) | ✅ 56.4s (score 0.75) | ~52s |
| `peer_agent` | ✅ 63.5s | ✅ 83.5s | ✅ 87.6s | ~78s |
| `aggregator_agent` | ✅ 440.4s (BUY, conf 0.83) | ❌ 357.8s (ver abajo) | ✅ 408.3s (BUY, conf 0.85) | ~420s (exitosos) |

**El único fallo (TSLA/aggregator) fue un bug del propio script de benchmark, no de FreeToken**: el fixture sintético usaba `"stocktwits_sentiment": "mixed"`, valor que el schema `SentimentSummary` del bot no acepta (`Literal["bullish","bearish","neutral"]`) — las 3 llamadas al LLM del aggregator para TSLA en realidad **completaron con éxito** (se ve en el log: 3× "LLM call succeeded" antes del `ValidationError`), el fallo ocurrió después, en código Python puro del propio `aggregator_agent.py` al construir `SentimentSummary` directo desde `state["sentiment"]`. Si se corrige el fixture (usar `"neutral"` en vez de `"mixed"`), no hay razón para esperar que falle.

### Señales de calidad (no solo "¿responde o no?")

- **Coherencia direccional correcta**: TSLA (fundamentals negativos a propósito) recibió scores bajos y consistentes en los 3 agentes que evalúan eso directamente — fundamental 0.38, técnico 0.35, sentimiento "bearish"/0.38 — mientras AAPL/MSFT (fundamentals positivos) recibieron 0.78/0.85/0.78 y "bullish". El modelo está razonando sobre los datos reales del prompt, no alucinando valores genéricos.
- **El mecanismo de auto-corrección por reintento (`client.py::complete()`) funcionó exactamente como está diseñado**: en 3 de las 6 llamadas del `aggregator_agent` (AAPL BullCase, TSLA BullCase, MSFT BullCase+FinalDecision), el modelo excedió el límite de caracteres de un campo de texto libre (`bull_summary` ≤500, `final_reasoning` ≤800) en el primer intento — el cliente le devolvió el error de validación de Pydantic en el prompt y el modelo se autocorrigió en el segundo intento, sin intervención externa.
- **Hallazgo de calidad real, no bloqueante**: el modelo tiende a escribir de más en los campos de resumen del `aggregator_agent` — pasó en 3 de 6 llamadas de aggregator (50%). No rompe el pipeline (el retry lo resuelve), pero sí añade latencia extra (~90-150s por reintento) y es información útil si en algún momento se ajustan los prompts/schemas — por ejemplo, subir el límite de caracteres de esos campos en vez de pelear con la verbosidad del modelo, ya que Groq/Gemini (modelos no-reasoning) probablemente no tengan este problema en la misma magnitud.
- **Latencia real de extremo a extremo**: ~35m46s para los 18 slots de agente (24 llamadas reales al LLM contando los 3 reintentos), sobre un ticker a la vez, sin paralelismo. Los agentes individuales (no-aggregator) promedian 45-90s cada uno; el `aggregator_agent` (3 llamadas encadenadas, con o sin reintento) promedia 350-440s. Esto es MUY por encima de la latencia de Groq (segundos, no minutos) — coherente con lo que ya anticipaba el plan original sobre el modelo "thinking" de FreeToken, y confirma que el "Nota de latencia" de la Etapa 3 original era acertada: para la cadencia mensual del bot esto probablemente es aceptable, pero para una corrida completa de `build_workflow()` sobre múltiples tickers en serie, el tiempo total podría ser de varias horas si los 6 agentes de cada ticker no corren en paralelo (el propio grafo de LangGraph sí paraleliza fundamental/technical/sentiment/macro entre sí — ver `workflow.py`).

### Conclusión de la Etapa 3 (agentes en secuencia)

**El gate de viabilidad técnica pasa.** FreeToken (nightly `0.1.2+g953565667`) sirve las 6 llamadas de agente reales del bot de forma confiable, con salida JSON válida y coherente con los datos de entrada, sin ningún cuelgue en ~24 llamadas reales al LLM. El único fallo fue un bug del harness de benchmark, no del proveedor.

### Punto 5 de la Etapa 3 — `graph.ainvoke()` completo vía `build_workflow()`, con datos de mercado REALES

A diferencia de la sección anterior (agentes invocados secuencialmente, uno a la vez, con `state` sintético hardcodeado), esto ejercita el pipeline real de producción de punta a punta: `analyze_ticker("AAPL", market="US", company_name="Apple Inc.")` → `graph.ainvoke()` sobre el grafo compilado de `build_workflow()` — incluyendo `fetch_data_node` con datos de mercado **reales** (yfinance como fuente, sin necesitar ninguna API key — Finnhub/FMP quedaron vacías a propósito) y el paralelismo real de LangGraph: los 4 agentes de análisis (`fundamental`, `technical`, `sentiment`, `macro`) se lanzan **concurrentemente**, algo que no se había probado antes (toda la Etapa 3 previa fue secuencial, un request a la vez).

**Resultado: ✅ ÉXITO END-TO-END.**

```
signal=BUY  confidence=0.65  risk_level=MEDIUM
llm_model_used=freetoken/Qwen3.6-35B-A3B-NVFP4
data_sources=['price_history', 'fundamentals', 'news', 'sentiment', 'peers']
disclaimer presente: True
```

Tiempo total: **1392s (~23.2 minutos)** para un ticker completo, sin paralelismo entre tickers (solo se corrió 1).

### Hallazgo crítico: bajo concurrencia real, el timeout de 180s de `client.py` es demasiado agresivo — y expone un problema real de la cadena de fallback

Con las 4 llamadas de análisis disparadas a la vez contra el mismo servidor FreeToken, se observó (vía el log del propio servidor, que reporta `#running-req`/`#queue-req`) que **FreeToken serializa la generación internamente pese a aceptar requests concurrentes** — no hay batching real de 4 requests en paralelo, se procesan una por una con las demás en cola. Combinado con que el cliente no pasa `max_tokens` (código real de `client.py`, no una limitación del benchmark) y que este checkpoint reasoning-heavy a veces genera 5,000-9,000+ tokens de razonamiento antes de la respuesta final, dos de los cuatro agentes (`technical_agent`, `macro_agent`) **superaron el timeout de 180s del cliente HTTP** mientras esperaban en cola + generaban:

- `technical_agent`: su primer intento a FreeToken tardó tanto (cola + ~7000 tokens de generación) que el cliente lo cortó a los 180s con `openai.APITimeoutError`.
- Como el `.env` de esta prueba tenía `PRIMARY_LLM=FALLBACK_LLM=freetoken`, `_get_provider_order()` arma una cadena `[freetoken, groq, gemini, ollama, freetoken]` (freetoken aparece dos veces: como primario y como fallback). Tras el timeout, cayó a `groq`/`gemini`/`ollama` — los tres fallan instantáneamente por falta de credenciales/servidor local — y **volvió a intentar `freetoken` una segunda vez** (por ser también el fallback), esta vez con éxito.
- Mismo patrón para `macro_agent`.
- `peer_agent` se saltó correctamente (sin `FINNHUB_API_KEY`, `peers_data` vacío → `peer_agent.py` devuelve `peer_analysis: None` sin llamar al LLM — degradación esperada, no un fallo).
- El `aggregator_agent` (3 llamadas encadenadas) tuvo el mismo patrón de "timeout + reintento exitoso" en su primera llamada (BullCase), y además 2 reintentos por validación de longitud (`bear_summary`/`final_reasoning` excediendo 500/800 caracteres — el mismo hallazgo de calidad de la sección anterior, confirmado otra vez).

**Implicación real para producción, más allá de este spike:**
1. **El timeout de 180s (agregado en esta misma sesión como mitigación al cuelgue original de FreeToken) es demasiado corto** para este modelo bajo carga concurrente real — un modelo reasoning-heavy sin `max_tokens` puede necesitar bastante más. Subirlo evitaría el ciclo de timeout+reintento, aunque el reintento "gratis" (por freetoken apareciendo 2 veces en la cadena) terminó salvando la corrida de todas formas.
2. **Esto solo funcionó porque `PRIMARY_LLM` y `FALLBACK_LLM` apuntaban ambos a `freetoken`.** Si en un despliegue real `FALLBACK_LLM=ollama` (el default de `.env.example`) y Ollama no está corriendo, un timeout de FreeToken bajo carga concurrente **rompería el agente por completo** (`AllProvidersExhausted`) en vez de reintentarse solo. Vale la pena decidir explícitamente en la Etapa 4 si FreeToken debería ser su propio fallback (además de primario) para beneficiarse de este comportamiento de reintento, o si conviene subir el timeout en cambio.
3. **No hay `max_tokens` en las llamadas reales del bot** (`client.py::_call_openai_compatible` no lo setea) — a diferencia del harness de benchmark de la sección anterior, que sí lo limitaba a 2000-3000. Sin tope, la latencia de una sola llamada puede variar de 45s a varios minutos según cuánto "piense" el modelo. Vale la pena decidir si esto se deja así (el bot es de cadencia mensual, no interactivo) o si conviene poner un `max_tokens` explícito para acotar la cola de espera bajo concurrencia.

### Conclusión final de la Etapa 3

**Ambos gates de la Etapa 3 pasan**: los 6 agentes responden de forma confiable y coherente (sección anterior), y el pipeline completo de producción (`build_workflow()` + concurrencia real + datos de mercado reales) termina con un `StockSuggestion` válido sin `AllProvidersExhausted` fatal. El hallazgo de la cadena de fallback + timeout es información valiosa y accionable para la Etapa 4, no un bloqueante — la corrida real se auto-recuperó sin intervención.

**Nota aparte, no relacionada con FreeToken**: `save_suggestion_node` falló al escribir en SQLite (`no such table: suggestions`) porque el harness de esta sesión nunca corrió las migraciones de Alembic — es un problema del entorno de prueba, no del LLM ni del pipeline; el objeto `StockSuggestion` se construyó y validó correctamente antes de ese paso.

## ACTUALIZACIÓN 2026-09-13: los 3 bugs de cuelgue parecen RESUELTOS en la nightly build

Se hizo `git pull` sobre `~/freetoken-dev/FreeToken` (194 archivos cambiados, 8693 inserciones desde el commit con el que se hizo todo el diagnóstico — un refactor grande de exactamente los subsistemas donde vivían los bugs: `offload_cache.py`, `qwen3_5_moe/gdn.py`, `qwen3_5_moe/moe.py`, y una reescritura de 1265 líneas en `qwen3_5_moe/weight.py` que introduce una capa de `QuantConfig` nueva para leer checkpoints). La versión en PyPI sigue clavada en 0.1.2 (sin cambios), pero el repo publica **wheels nightly** vía GitHub Releases (`tag: nightly`) — se instaló `freetoken==0.1.2+g953565667` (build del 2026-09-09, exactamente desde el HEAD que se bajó) reemplazando la 0.1.2 estable en el mismo venv:

```bash
# Wheels descargadas desde:
# https://github.com/FlashML-org/FreeToken/releases/download/nightly/freetoken-0.1.2%2Bg953565667-cp312-cp312-linux_x86_64.whl
# https://github.com/FlashML-org/FreeToken/releases/download/nightly/freetoken_kernel_cache-0.1.2%2Bcu130.g953565667-py3-none-linux_x86_64.whl
uv pip install --force-reinstall --no-deps freetoken-0.1.2+g953565667-cp312-cp312-linux_x86_64.whl freetoken_kernel_cache-0.1.2+cu130.g953565667-py3-none-linux_x86_64.whl
```

**Se re-corrió la secuencia de reproducción exacta de los 3 bugs documentados abajo** (config 100% default: `--attention-backend fi` auto-seleccionado + `--moe-backend offload` auto-seleccionado + `--cache-type radix`, sin ningún flag ni parche manual — el escenario que el bot real usaría out-of-the-box), en un arranque en frío del servidor:

1. **Bug #1 (`rmsnorm_cute` de FlashInfer, config default `fi`+`offload`)**: el request con el schema completo de 8 campos, que ANTES se colgaba indefinidamente en esta exacta configuración → **ahora responde en 6.7s** sin ningún flag especial.
2. **Bug #3 (GDN, prefijo compartido + extensión cruzando `CHUNK_SIZE`)**: la secuencia exacta (request A de 4 campos → request B de 5 campos que extiende el prefijo de A) → **ahora responde en 2.0-2.3s**, sin cuelgue.
3. **Prueba end-to-end completa**: request con el schema real de `FundamentalAnalysis` (8 campos), `temperature=0.1` (igual que `client.py`), `max_tokens=3000` → `finish_reason: "stop"`, JSON válido con las 8 keys esperadas, parseado correctamente por la lógica real de `_strip_think_tags`/`_extract_json` del cliente. **59s de latencia total** (2532 tokens de completion, mayormente razonamiento).

Se repitió la secuencia completa 2 veces (una vez con cache caliente, una vez con arranque en frío) — **cero cuelgues en ambas corridas**. `nvidia-smi` confirmó GPU en reposo (0-1%, ~45W) entre requests, sin ningún proceso zombie.

**No se re-probó específicamente el bug #2** (`offload_cache.py`, el que solo aparecía con `--attention-backend triton` explícito) ni el bug #4 (`layernorm_gated.py`, con `--cache-type naive`/`--moe-backend cpu`) — no hizo falta, porque el escenario relevante para el bot real es la configuración default (que ya sabíamos disparaba los bugs #1 y #3), y esa ahora funciona limpio de punta a punta.

**Conclusión revisada**: lo que en la sesión anterior se documentó como "múltiples bugs de kernel CUDA irresolubles, FreeToken no viable" puede haber sido simplemente **inmadurez de la versión 0.1.2 recién publicada** (cortada el 19 de agosto), ya resuelta ~3 semanas después en el desarrollo activo del proyecto. **Esto reabre la posibilidad real de la Etapa 2/3** — con la salvedad de que se está corriendo sobre una build nightly no publicada oficialmente en PyPI, no una release estable.

**Siguiente paso recomendado**: correr el benchmark completo de la Etapa 3 (los 6 agentes reales contra tickers reales) sobre esta nightly, ya que el gate técnico de "¿responde sin colgarse?" parece superado. Si eso también sale bien, decidir cómo pinnear la dependencia en producción (nightly wheel específica vs. esperar un tag de release oficial — las nightlies son "rolling", el asset de hoy puede desaparecer/cambiar mañana, así que no es ideal fijarse a esa URL a largo plazo).

## Estado al cortar la sesión (2026-09-07, ~23:07) — para retomar

- Se estaba descargando `Qwen/Qwen3.6-35B-A3B-FP8` (checkpoint FP8 del mismo modelo, para ver si evita los 4 bugs de kernel encontrados con NVFP4) — quedó a mitad de camino (~20GB de ~35GB) en `~/.cache/huggingface/hub/models--Qwen--Qwen3.6-35B-A3B-FP8`. La descarga es resumible (huggingface_hub), retomar con:
  ```bash
  cd ~/freetoken-spike && source .venv/bin/activate && export PATH=/usr/local/cuda/bin:$PATH
  ft serve --model Qwen/Qwen3.6-35B-A3B-FP8 --cuda-graph-max-bs 0
  ```
  (probar primero con flags default; si carga, repetir la secuencia de reproducción de 2 requests — ver `req_constraints.json`/`req_5field.json` en el scratchpad de la sesión, o reconstruir el schema de 4→5 campos de `FundamentalAnalysis` — para ver si el bug persiste con este checkpoint.)
- El fix de `offload_cache.py` (bug #2) sigue aplicado en `~/freetoken-spike/.venv/lib/python3.12/site-packages/freetoken/moe/offload_cache.py` — **es un cambio manual al paquete instalado, no persiste si se reinstala el venv**. El mismo fix, listo para copiar, también está aplicado en el clon del repo en `~/freetoken-dev/FreeToken/python/freetoken/moe/offload_cache.py` (para el PR eventual).
- Todos los procesos de FreeToken y `cuda-gdb` quedaron matados y la GPU liberada antes de cortar.
- Pendiente de decisión con el usuario: si el FP8 tampoco funciona limpio, cerrar la investigación acá y armar el PR (fix de `offload_cache.py`) + 3 issues/comentarios (rmsnorm_cute, gdn.py, layernorm_gated.py) con toda la evidencia de este documento — el usuario todavía no pidió explícitamente abrir el PR, solo autorizó "intentar resolverlo".

## Archivos críticos

- `stock-bot/app/config.py`
- `stock-bot/app/llm/client.py`
- `stock-bot/app/data/rate_limiter.py`
- `stock-bot/.env.example`
- `stock-bot/SETUP.md`
