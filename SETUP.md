# StockBot — Guía de Inicio

Sistema de sugerencias de inversión mensual (US / Crypto / Perú).
**Nunca ejecuta órdenes de compra/venta. Solo sugerencias.**

---

## Índice

1. [Requisitos previos](#1-requisitos-previos)
2. [API Keys necesarias](#2-api-keys-necesarias)
3. [Configuración paso a paso](#3-configuración-paso-a-paso)
4. [Levantar el proyecto](#4-levantar-el-proyecto)
5. [Verificar que todo funciona](#5-verificar-que-todo-funciona)
6. [Límites de APIs gratuitas](#6-límites-de-apis-gratuitas)
7. [Solución de problemas comunes](#7-solución-de-problemas-comunes)

---

## 1. Requisitos previos

| Herramienta    | Versión mínima           | Para qué                                      |
| -------------- | -------------------------- | ---------------------------------------------- |
| Python         | 3.11+                      | Ejecutar la API y el dashboard                 |
| Docker Desktop | 4.x                        | Redis + PostgreSQL (opcional en modo local)    |
| Docker Compose | incluido en Docker Desktop | Orquestar servicios                            |
| Ollama         | última                    | Fallback LLM local (opcional pero recomendado) |

### Verificar instalaciones

```bash
python --version          # debe mostrar 3.11 o superior
docker --version
docker compose version
ollama --version          # opcional
```

---

## 2. API Keys necesarias

### Mínimo indispensable (para que el bot funcione)

Necesitas **al menos una key de LLM**. Con solo Groq ya arranca.

| API               | Dónde obtenerla                          | Tier gratuito      | Uso en el bot                |
| ----------------- | ----------------------------------------- | ------------------ | ---------------------------- |
| **Groq**    | [console.groq.com](https://console.groq.com) | 30 RPM / 1,000 RPD | LLM primario (Llama 3.3 70B) |
| **Finnhub** | [finnhub.io](https://finnhub.io)             | 60 RPM             | Precios y noticias US        |

### Recomendadas (mejoran cobertura)

| API                          | Dónde obtenerla                                             | Tier gratuito                      | Uso en el bot                   |
| ---------------------------- | ------------------------------------------------------------ | ---------------------------------- | ------------------------------- |
| **Google AI (Gemini)** | [aistudio.google.com](https://aistudio.google.com/apikey)       | 10 RPM / 1,500 RPD                 | Fallback LLM + contextos largos |
| **FMP**                | [financialmodelingprep.com](https://financialmodelingprep.com)  | 250 RPD                            | Fundamentales US                |
| **Alpha Vantage**      | [alphavantage.co](https://www.alphavantage.co/support/#api-key) | 25 RPD                             | Noticias con sentimiento        |
| **CoinGecko**          | [coingecko.com/api](https://www.coingecko.com/en/api)           | 30 RPM (sin key también funciona) | Datos crypto                    |
| **Reddit**             | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)      | ilimitado                          | Sentimiento (WSB, r/stocks)     |

### Opcionales (sin estas el bot sigue funcionando)

| API          | Uso                                                         |
| ------------ | ----------------------------------------------------------- |
| OpenRouter   | LLM alternativo                                             |
| Ollama local | Fallback LLM sin internet — requiere GPU o paciencia       |
| SEC EDGAR    | Filings 10-K (solo necesitas poner tu nombre/email, no key) |

> **yfinance no requiere key.** Funciona directo con impersonación de Chrome via `curl_cffi`.

---

## 3. Configuración paso a paso

### 3.1 Entrar al directorio del proyecto

```bash
cd stock-bot
```

### 3.2 Crear el archivo `.env`

```bash
cp .env.example .env
```

Edita `.env` y completa al menos estas variables:

```env
# MÍNIMO PARA ARRANCAR
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
FINNHUB_API_KEY=xxxxxxxxxxxxxxxxxxxx

# RECOMENDADO
GOOGLE_API_KEY=AIzaxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FMP_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ALPHA_VANTAGE_KEY=xxxxxxxxxxxxxxxxxxxx
COINGECKO_API_KEY=CG-xxxxxxxxxxxxxxxxxxxxxxxxxx  # opcional, funciona sin ella
REDDIT_CLIENT_ID=xxxxxxxxxxxx
REDDIT_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxx
REDDIT_USER_AGENT=StockBot/1.0 by tu_usuario_reddit

# REQUERIDO para SEC EDGAR (pon tu nombre y email real)
SEC_IDENTITY_NAME=Tu Nombre
SEC_IDENTITY_EMAIL=tu@email.com

# BASE DE DATOS — dejar sqlite para pruebas locales
DATABASE_URL=sqlite:///./stockbot.db

# REDIS — cambiar si usas Docker
REDIS_URL=redis://localhost:6379/0
```

> **Nunca** subas el archivo `.env` a Git. Ya está en `.gitignore`.

### 3.3 Crear entorno virtual e instalar dependencias

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt   # solo si vas a correr tests
```

La instalación tarda ~2-3 minutos. Si falla `psycopg2-binary`, ignóralo si usas SQLite.

### 3.4 Instalar browsers para Playwright (scraper BVL fallback)

```bash
playwright install chromium
```

### 3.5 Levantar Redis (requerido)

**Opción A — Docker (recomendado):**

```bash
docker compose up -d redis
```

**Opción B — Redis local instalado:**

```bash
# Windows (con Redis instalado via winget o chocolatey)
redis-server

# Mac
brew services start redis
```

### 3.6 Crear la base de datos y correr migraciones

```bash
# Crear tablas (SQLite: crea el archivo stockbot.db automáticamente)
alembic upgrade head
```

Si ves `Target database is not up to date` o errores de migración:

```bash
alembic stamp head   # marca el estado actual como al día
alembic upgrade head # re-intenta
```

### 3.7 Poblar el watchlist inicial (13 tickers de prueba)

```bash
python -m app.scripts.seed_watchlist
```

Debería mostrar:

```
  ✓ AAPL (US)
  ✓ MSFT (US)
  ...
Seeded 13 tickers.
```

### 3.8 (Opcional) Configurar Ollama como fallback local

```bash
# Instalar Ollama desde https://ollama.com
ollama pull qwen2.5:32b   # 20GB — solo si tienes GPU
# o un modelo más liviano:
ollama pull qwen2.5:7b    # 4.7GB
```

Si usas un modelo diferente, cambia `OLLAMA_MODEL` en `.env`.

### 3.9 (Opcional, experimental) Configurar FreeToken como LLM local

[FreeToken](https://github.com/FlashML-org/FreeToken) es un motor de inferencia que sirve modelos MoE grandes (ej. Qwen3.6-35B-A3B) en GPUs de consumo, tratando VRAM+RAM+disco como una jerarquía de memoria elástica. Alternativa a Ollama con más capacidad de modelo, pero con requisitos más estrictos.

**Requisitos:** Linux x86_64 nativo (sin WSL2/Docker oficial) + GPU NVIDIA con driver r580+/CUDA 13 + CUDA 13 toolkit (`nvcc` en el `PATH`) + suficiente RAM/disco para el modelo elegido (una cuantización NVFP4 de un MoE ~35B ronda 20GB en disco).

```bash
# CUDA 13 toolkit (si no lo tienes) — repo oficial de NVIDIA, ejemplo Ubuntu 24.04:
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb && sudo apt update
sudo apt install -y cuda-toolkit-13-2   # usar la versión que matchee tu driver (ver `nvidia-smi`)
export PATH=/usr/local/cuda/bin:$PATH   # agregar a ~/.bashrc para persistir

# uv + FreeToken en un venv dedicado (no el de stock-bot)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv ~/freetoken-spike/.venv --python 3.12
source ~/freetoken-spike/.venv/bin/activate
uv pip install "freetoken[accel]"

# Servir el modelo (primera vez compila kernels CUDA JIT, tarda ~1 min)
ft serve --model nvidia/Qwen3.6-35B-A3B-NVFP4
```

Esperar el log `API server is ready to serve on 127.0.0.1:1919`, luego confirmar con:

```bash
curl http://127.0.0.1:1919/v1/models
```

**Nota conocida:** al menos para el checkpoint `nvidia/Qwen3.6-35B-A3B-NVFP4`, el downloader de `ft serve` no trae `model.safetensors.index.json` ni `hf_quant_config.json` aunque existen en el repo de Hugging Face — si falla con `FileNotFoundError` en la carga de "expert banks", bajalos manualmente antes de reintentar (sin necesidad de rehacer la descarga de los pesos):

```bash
python3 -c "
from huggingface_hub import hf_hub_download
for f in ['model.safetensors.index.json', 'hf_quant_config.json']:
    hf_hub_download('nvidia/Qwen3.6-35B-A3B-NVFP4', f)
"
```

Para activarlo, poné `PRIMARY_LLM=freetoken` (o `FALLBACK_LLM=freetoken`) en `.env`, con `FREETOKEN_BASE_URL`/`FREETOKEN_MODEL` apuntando al servidor levantado arriba. Es un modelo con razonamiento ("thinking") — responde con una cadena de pensamiento antes del JSON final, así que las respuestas tardan más que Groq/Gemini en producir el resultado final.

---

## 4. Levantar el proyecto

### Modo A — Local (recomendado para desarrollo)

Abre **dos terminales**:

**Terminal 1 — API:**

```bash
# Con el .venv activado
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Dashboard:**

```bash
streamlit run dashboard/app.py --server.port 8501
```

Accede a:

- API: [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI)
- Dashboard: [http://localhost:8501](http://localhost:8501)

### Modo B — Docker Compose completo

Usa PostgreSQL en vez de SQLite. Edita `.env` primero:

```env
DATABASE_URL=postgresql://stockbot:stockbot_dev@localhost:5432/stockbot
```

Luego:

```bash
docker compose up -d
```

Espera ~30 segundos a que los servicios estén healthy, luego:

```bash
# Migraciones dentro del contenedor
docker compose exec api alembic upgrade head

# Seed del watchlist
docker compose exec api python -m app.scripts.seed_watchlist
```

---

## 5. Verificar que todo funciona

### 5.1 Health check

```bash
curl http://localhost:8000/api/health
# Esperado: {"status":"ok","timestamp":"2026-..."}
```

### 5.2 Ver el watchlist

```bash
curl http://localhost:8000/api/watchlist/
# Esperado: lista de 13 tickers en JSON
```

### 5.3 Ejecutar tu primer análisis

```bash
# Análisis de AAPL (~30-90 segundos dependiendo del LLM)
curl -X POST "http://localhost:8000/api/analysis/AAPL?market=US"
```

Respuesta esperada (resumen):

```json
{
  "ticker": "AAPL",
  "signal": "BUY",
  "confidence": 0.72,
  "disclaimer": "Not financial advice. For informational purposes only.",
  "llm_model_used": "groq/llama-3.3-70b-versatile",
  "data_sources": ["price_history", "fundamentals", "news", "sentiment"]
}
```

### 5.4 Correr los tests

```bash
# Tests de agentes (no necesitan APIs reales, usan mocks)
pytest tests/test_agents.py -v

# Tests de API (tampoco necesitan APIs reales)
pytest tests/test_api.py -v

# Tests de rate limiter
pytest tests/test_rate_limiter.py -v

# Todos los tests
pytest -v
```

---

## 6. Límites de APIs gratuitas

El bot respeta estos límites automáticamente via Redis (rate limiter integrado):

| Proveedor            | Límite gratuito    | Qué pasa al llegar al límite               |
| -------------------- | ------------------- | -------------------------------------------- |
| Groq (Llama 3.3 70B) | 30 RPM / 1,000 RPD  | Cambia a Gemini automáticamente             |
| Gemini Flash         | 10 RPM / 1,500 RPD  | Cambia a Ollama automáticamente             |
| Ollama               | Sin límite         | —                                           |
| Finnhub              | 60 RPM              | Espera hasta el siguiente minuto             |
| FMP                  | 250 RPD             | Usa yfinance como fallback                   |
| Alpha Vantage        | 25 RPD              | Reservado solo para noticias con sentimiento |
| CoinGecko            | 30 RPM / 10,000 RPD | Espera hasta el siguiente minuto             |
| yfinance             | Sin límite oficial | curl_cffi impersona Chrome para evitar 429s  |

> Con 13 tickers en el watchlist y análisis semanal, el consumo diario promedio es ~150 llamadas LLM — dentro del tier gratuito de Groq.

---

## 7. Solución de problemas comunes

### `redis.exceptions.ConnectionError`

Redis no está corriendo.

```bash
docker compose up -d redis
# o verificar: redis-cli ping  → debe responder PONG
```

### `ModuleNotFoundError: No module named 'app'`

Ejecuta los comandos desde dentro del directorio `stock-bot/`, con el `.venv` activado.

```bash
cd stock-bot
.venv\Scripts\activate   # Windows
uvicorn app.main:app --reload
```

### `alembic.util.exc.CommandError: Can't locate revision`

```bash
alembic stamp head
alembic upgrade head
```

### El análisis tarda mucho o da timeout

- Verifica que Groq API Key esté correcta en `.env`
- Aumenta el timeout en el dashboard si lanzas análisis desde ahí
- El análisis completo con todos los agentes puede tardar 60-120 segundos

### `429 Too Many Requests` en yfinance

Es normal ocasionalmente. El bot usa `curl_cffi` para impersonar Chrome y reducir estos errores. Si persiste, espera unos minutos.

### `zeep.exceptions.Error` al analizar tickers BVL peruanos (.LM)

El SOAP de SMV puede tardar 10-30 segundos o no estar disponible. El bot usa yfinance como fallback automáticamente. No es un error bloqueante.

### Dashboard muestra pantalla en blanco

Verifica que la API esté corriendo primero:

```bash
curl http://localhost:8000/api/health
```

El dashboard depende de la API — no accede directamente a la base de datos.

### `ImportError: cannot import name 'SessionLocal'`

Asegúrate de correr la versión más reciente del código. El seed usa `SyncSessionLocal` internamente (ya corregido en `app/scripts/seed_watchlist.py`).

---

## Referencia rápida de comandos

```bash
# Levantar Redis
docker compose up -d redis

# API
uvicorn app.main:app --reload --port 8000

# Dashboard
streamlit run dashboard/app.py

# Migrar DB
alembic upgrade head

# Seed watchlist
python -m app.scripts.seed_watchlist

# Correr tests
pytest -v

# Análisis manual de un ticker
curl -X POST "http://localhost:8000/api/analysis/AAPL?market=US"

# Ver sugerencias guardadas
curl http://localhost:8000/api/suggestions/AAPL

# Añadir ticker al watchlist
curl -X POST http://localhost:8000/api/watchlist/ \
  -H "Content-Type: application/json" \
  -d '{"ticker":"TSLA","name":"Tesla Inc.","market":"US","sector":"Automotive"}'
```
