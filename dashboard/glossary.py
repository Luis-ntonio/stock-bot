"""Glosario de jerga financiera + helpers para explicar el output del bot
a alguien sin experiencia en inversiones, sin estorbarle a quien sí la
tiene (tooltips nativos del navegador — nadie los ve si no pasa el mouse,
y un usuario avanzado los ignora sin esfuerzo)."""
import html
import re

GLOSSARY: dict[str, str] = {
    "P/E": "Precio/Ganancias — cuántas veces el precio de la acción supera sus ganancias anuales. Más alto no es necesariamente malo: puede reflejar expectativas de crecimiento, o puede estar sobrevalorado.",
    "P/B": "Precio/Valor en libros — compara el precio de la acción contra el valor contable (activos menos deudas) de la empresa.",
    "PEG": "P/E ajustado por crecimiento (P/E ÷ % de crecimiento). Un P/E alto puede ser razonable si el crecimiento también lo es — un PEG cercano a 1 suele considerarse un balance justo entre precio y crecimiento.",
    "FCF yield": "Flujo de caja libre ÷ precio de la acción — cuánto efectivo genera realmente la empresa en relación a lo que cuesta comprarla. Más alto suele ser mejor.",
    "RSI": "Índice de Fuerza Relativa (0-100) — mide si una acción está 'sobrecomprada' (arriba de 70, podría corregir a la baja) o 'sobrevendida' (abajo de 30, podría rebotar).",
    "MACD": "Indicador de momentum que compara dos promedios móviles del precio — MACD positivo suele asociarse a tendencia alcista de corto plazo, negativo a bajista.",
    "SMA": "Media Móvil Simple — el precio promedio de los últimos N días (ej. SMA50 = promedio de 50 días), usada para suavizar el ruido diario y ver la tendencia.",
    "golden cross": "Cuando el promedio de 50 días cruza por ARRIBA del de 200 días — lectura técnica alcista de mediano plazo.",
    "death cross": "Cuando el promedio de 50 días cruza por DEBAJO del de 200 días — lectura técnica bajista de mediano plazo.",
    "cup_and_handle": "Patrón técnico de 'taza con asa' — el precio forma una U seguida de una pequeña consolidación. Suele interpretarse como señal alcista si se confirma con volumen.",
    "head_and_shoulders": "Patrón técnico de 'cabeza y hombros' — tres picos donde el del medio es el más alto. Suele interpretarse como señal bajista (reversión de tendencia alcista).",
    "EV/EBITDA": "Valor de la empresa ÷ ganancias antes de intereses, impuestos, depreciación y amortización — otra forma de medir si una acción está cara, útil para comparar empresas con distinta estructura de deuda.",
    "debt/equity": "Deuda ÷ patrimonio neto — cuánto debe la empresa en relación a lo que vale. Más alto implica más riesgo financiero (más obligaciones que cumplir pase lo que pase con el negocio).",
    "EPS": "Ganancia por acción (Earnings Per Share) — la ganancia neta de la empresa dividida por el número de acciones.",
    "VIX": "Índice de volatilidad del mercado (a veces llamado 'índice del miedo') — más alto implica más nerviosismo/incertidumbre en el mercado en general, no de una acción puntual.",
    "YoY": "Year over Year — comparación contra el mismo período del año anterior (ej. 'ingresos +28% YoY' = 28% más que hace un año).",
}

# Orden por longitud descendente para no matchear "P/E" dentro de "P/EBITDA"-like text.
_SORTED_TERMS = sorted(GLOSSARY.items(), key=lambda kv: -len(kv[0]))

_TOOLTIP_STYLE = "border-bottom:1px dotted #6e7681;cursor:help;"


def annotate_terms(text: str) -> str:
    """Escapa el texto (nunca confiar en texto generado por LLM como HTML
    crudo) y envuelve la PRIMERA ocurrencia de cada término del glosario
    con un tooltip nativo del navegador (atributo title=, sin JS ni
    dependencias nuevas)."""
    if not text:
        return text
    escaped = html.escape(text)
    for term, explanation in _SORTED_TERMS:
        pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)
        tooltip = html.escape(explanation, quote=True)

        def _wrap(m: re.Match, _tooltip=tooltip) -> str:
            return f'<span title="{_tooltip}" style="{_TOOLTIP_STYLE}">{m.group(0)}</span>'

        escaped = pattern.sub(_wrap, escaped, count=1)
    return escaped


_ACTION_ES = {"BUY": "comprar", "HOLD": "mantener lo que ya tenés (ni comprar ni vender)", "SELL": "vender"}


def plain_language_summary(signal: str, confidence: float, risk_level: str) -> str:
    """Una frase determinística (no generada por LLM — gratis, consistente,
    sin latencia extra) que traduce la señal técnica a lenguaje simple."""
    action = _ACTION_ES.get(signal, signal.lower())
    conf_word = "alta" if confidence >= 0.75 else "moderada" if confidence >= 0.60 else "baja"
    risk_es = {"low": "bajo", "medium": "medio", "high": "alto", "very_high": "muy alto"}.get(
        (risk_level or "").lower(), risk_level
    )
    return (
        f"En términos simples: el modelo sugiere **{action}**, con confianza {conf_word} "
        f"({confidence*100:.0f}%) y nivel de riesgo {risk_es}."
    )


def render_glossary_expander(st_module) -> None:
    """st_module es el propio módulo `streamlit` — se pasa como parámetro
    para no importar streamlit en un módulo que también se usa fuera del
    dashboard (ej. si algún día se reusa server-side)."""
    with st_module.expander("📖 Glosario de términos", expanded=False):
        for term, explanation in sorted(GLOSSARY.items()):
            st_module.markdown(f"**{term}** — {explanation}")
