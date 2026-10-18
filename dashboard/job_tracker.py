"""Tracking de jobs en background (análisis/revisión de posición) del lado
del dashboard. Streamlit no tiene push — así que la forma de "notificar
cuando termina" sin agregar dependencias nuevas es: guardar los job_ids
activos en session_state, consultarlos en cada render, mostrar un toast
cuando cambian de estado, y volver a correr el script cada pocos segundos
mientras haya alguno pendiente.

IMPORTANTE sobre el orden de llamadas en la página: poll_tracked_jobs() debe
llamarse cerca del tope (actualiza el estado para que el resto del script lo
lea bien, ej. el botón deshabilitado) pero NUNCA debe hacer st.rerun() ella
misma — si lo hiciera, cortaría la ejecución ahí mismo y el resto de la
página (el botón, el contenido) jamás llegaría a dibujarse mientras haya un
job activo. autorefresh_if_active() es la que hace sleep+rerun, y va al
FINAL del script, después de que todo ya se renderizó."""
import time
import streamlit as st
from dashboard.api_client import fetch_job

_SESSION_KEY = "sb_active_jobs"
_POLL_SECONDS = 4


def track_job(job_id: int, key: str, ticker: str, label: str) -> None:
    """key identifica de forma única lo que se está siguiendo para el
    chequeo de "¿ya hay algo corriendo?" — el ticker solo (para análisis)
    o f"pos:{position_id}" (para revisión, porque puede haber dos compras
    del mismo ticker). ticker es solo para mostrar en el toast."""
    jobs = st.session_state.setdefault(_SESSION_KEY, {})
    jobs[job_id] = {"key": key, "ticker": ticker, "label": label}


def has_active_job(key: str | None = None) -> bool:
    jobs = st.session_state.get(_SESSION_KEY, {})
    if key is None:
        return bool(jobs)
    return any(m["key"] == key for m in jobs.values())


def poll_tracked_jobs(on_done=None) -> None:
    """Llamar una vez cerca del tope de la página, ANTES de renderizar
    cualquier cosa que dependa de has_active_job(). Consulta cada job
    trackeado; si terminó (done/failed) dispara un toast y lo saca del
    tracking. No bloquea ni hace rerun — eso es trabajo de
    autorefresh_if_active()."""
    jobs = st.session_state.get(_SESSION_KEY, {})
    if not jobs:
        return

    still_active = {}
    for job_id, meta in jobs.items():
        job = fetch_job(job_id)
        if job is None:
            continue
        status = job["status"]
        if status in ("queued", "running"):
            still_active[job_id] = meta
        elif status == "done":
            st.toast(f"✅ {meta['label']} de {meta['ticker']} completo", icon="✅")
            if on_done:
                on_done(meta, job)
        elif status == "failed":
            err = (job.get("error") or "")[:160]
            st.toast(f"❌ {meta['label']} de {meta['ticker']} falló: {err}", icon="❌")

    st.session_state[_SESSION_KEY] = still_active


def autorefresh_if_active() -> None:
    """Llamar al FINAL de la página, después de que todo el contenido ya se
    renderizó. Si queda algún job activo, espera un poco y reruns — así la
    próxima vuelta vuelve a pollear desde el tope con estado fresco."""
    if st.session_state.get(_SESSION_KEY):
        time.sleep(_POLL_SECONDS)
        st.rerun()
