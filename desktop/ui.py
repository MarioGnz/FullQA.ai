#!/usr/bin/env python3
"""FullQA.ai Desktop — native PyQt6 UI."""
from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    QByteArray, QObject, QProcess, QSettings, QSize, Qt, QThread, QTimer, QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QDesktopServices, QFont, QImage, QPixmap, QTextDocument,
)
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
    QStackedWidget,
    QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

API        = "http://localhost:8000"
# Acceptance criteria longer than this are trimmed by the API before they
# reach the model (claude_gen.MAX_AC_CHARS) - warn in the UI before that.
AC_MAX_CHARS = 4000
REFRESH_MS = 15_000
HEALTH_MS  = 10_000


def _settings() -> QSettings:
    """Local user settings (theme, per-session report context).

    The storage identity stays "QA-DocAI" (the product's former name) — 
    renaming it would orphan every setting users already have.
    """
    return QSettings("QA-DocAI", "QA-DocAI")

# ── i18n ─────────────────────────────────────────────────────────────────────
_ui_lang = "es"
_TR: dict[str, dict[str, str]] = {
    "ui_lang_lbl":      {"es": "Idioma UI:",             "en": "UI Language:"},
    "refresh":          {"es": "Actualizar",             "en": "Refresh"},
    "connecting":       {"es": "Conectando...",          "en": "Connecting..."},
    "api_online":       {"es": "API Online",             "en": "API Online"},
    "api_offline":      {"es": "API Offline",            "en": "API Offline"},
    "tab_sessions":     {"es": "Sesiones",               "en": "Sessions"},
    "tab_record":       {"es": "Grabar",                 "en": "Record"},
    "tab_overview":     {"es": "  Resumen  ",            "en": "  Overview  "},
    "tab_events":       {"es": "  Eventos  ",            "en": "  Events  "},
    "tab_report":       {"es": "  Reporte  ",            "en": "  Report  "},
    "sessions_title":   {"es": "Sesiones",               "en": "Sessions"},
    "search_ph":        {"es": "Buscar...",              "en": "Search..."},
    "delete_btn":       {"es": "  Eliminar sesion",      "en": "  Delete session"},
    "rec_lang_lbl":     {"es": "Idioma docs:",           "en": "Docs language:"},
    "rec_mic_lbl":      {"es": "Microfono:",             "en": "Microphone:"},
    "rec_no_audio":     {"es": "Sin narracion (solo pantalla)", "en": "No audio (screen only)"},
    "rec_refresh_tip":  {"es": "Actualizar lista de microfonos", "en": "Refresh microphone list"},
    "rec_start":        {"es": "Iniciar Grabacion",      "en": "Start Recording"},
    "rec_stop":         {"es": "Detener Grabacion",      "en": "Stop Recording"},
    "rec_saving":       {"es": "Guardando sesion...",    "en": "Saving session..."},
    "rec_recording":    {"es": "Grabando...",            "en": "Recording..."},
    "rec_saved":        {"es": "Sesion guardada",        "en": "Session saved"},
    "rec_audio_off":    {"es": "Audio desactivado: ",    "en": "Audio disabled: "},
    "ov_ctx_lbl":       {"es": "Contexto para el reporte:", "en": "Context for report:"},
    "ov_title_ph":      {"es": "Titulo del testing (ej: Login flow, Checkout)",
                          "en": "Testing title (e.g.: Login flow, Checkout)"},
    "ov_desc_ph":       {"es": "Descripcion breve (ej: Verificar que usuario puede iniciar sesion)",
                          "en": "Brief description (e.g.: Verify user can log in)"},
    "ov_ac_lbl":        {"es": "Criterios de aceptación del ticket",
                          "en": "Ticket acceptance criteria"},
    "ov_ac_opt":        {"es": "opcional",                "en": "optional"},
    "ov_ac_ph":         {"es": ("Pega aquí los criterios de aceptación del ticket, uno por línea:\n"
                                "AC1 - El usuario puede iniciar sesión con credenciales válidas\n"
                                "AC2 - Se muestra un error con credenciales inválidas"),
                          "en": ("Paste the ticket acceptance criteria here, one per line:\n"
                                 "AC1 - The user can log in with valid credentials\n"
                                 "AC2 - An error is shown for invalid credentials")},
    "ov_ac_hint":       {"es": ("Se guardan en esta sesión. La IA los trata como el requisito "
                                "a verificar: cada caso de prueba indica qué criterio cubre y "
                                "el reporte cierra con una tabla de cobertura."),
                          "en": ("Saved with this session. The AI treats them as the requirement "
                                 "under test: each test case names the criteria it covers and the "
                                 "report closes with a coverage table.")},
    "ov_ac_paste":      {"es": "Pegar",                   "en": "Paste"},
    "ov_ac_paste_tip":  {"es": "Pegar los criterios desde el portapapeles",
                          "en": "Paste the criteria from the clipboard"},
    "ov_ac_clear":      {"es": "Limpiar",                 "en": "Clear"},
    "ov_ac_chars":      {"es": "{n} caracteres",          "en": "{n} characters"},
    "ov_ac_over":       {"es": "{n} caracteres · se recortará a {m}",
                          "en": "{n} characters - will be trimmed to {m}"},
    "ov_sec_lbl":       {"es": "Secciones a generar:",  "en": "Sections to generate:"},
    "ov_lang_lbl":      {"es": "Idioma del reporte:",   "en": "Report language:"},
    "ov_generate":      {"es": "Generar Documentacion", "en": "Generate Documentation"},
    "ov_regenerate":    {"es": "Regenerar",             "en": "Regenerate"},
    "ov_generating":    {"es": "Generando...", "en": "Generating..."},
    "ov_ready":         {"es": "Documentacion lista",   "en": "Documentation ready"},
    "ov_no_sec_title":  {"es": "Sin secciones",         "en": "No sections"},
    "ov_no_sec_msg":    {"es": "Selecciona al menos una seccion.", "en": "Select at least one section."},
    "rp_rendered":      {"es": "Renderizado",           "en": "Rendered"},
    "rp_copy":          {"es": "Copiar",                "en": "Copy"},
    "dp_placeholder":   {"es": "<- Selecciona una sesion", "en": "<- Select a session"},
    "dp_rp_hint":       {"es": "Haz clic en 'Reporte' para cargar.", "en": "Click 'Report' to load."},
    "dp_rp_loading":    {"es": "Cargando reporte...",   "en": "Loading report..."},
    "dp_rp_none":       {"es": "Reporte no disponible.\nGenera la documentacion primero.",
                          "en": "Report unavailable.\nGenerate documentation first."},
    "sb_refreshing":    {"es": "Actualizando sesiones...", "en": "Refreshing sessions..."},
    "del_title":        {"es": "Eliminar sesion",        "en": "Delete session"},
    "del_msg":          {"es": "Eliminar esta sesion?",  "en": "Delete this session?"},
    "del_warning":      {"es": ("Se eliminara el registro, el reporte y los archivos de captura.\n"
                                "Esta accion no se puede deshacer."),
                          "en": ("The record, report and capture files will be deleted.\n"
                                 "This action cannot be undone.")},
    "del_err_title":    {"es": "Error al eliminar",      "en": "Error deleting"},
    "gen_err_title":    {"es": "Error de generacion",    "en": "Generation error"},
    "img_copy":         {"es": "Copiar imagen",          "en": "Copy image"},
    "img_copied":       {"es": "Copiada!",               "en": "Copied!"},
    "img_close":        {"es": "Cerrar",                 "en": "Close"},
    "img_click_hint":   {"es": "Clic en imagen para ampliar/copiar",
                          "en": "Click image to enlarge / copy"},
    "ov_provider_lbl":  {"es": "Proveedor AI:",          "en": "AI Provider:"},
    "ov_model_lbl":     {"es": "Modelo:",                "en": "Model:"},
    "ov_test_conn":     {"es": "Probar conexión",        "en": "Test connection"},
    "ov_test_testing":  {"es": "Probando...",            "en": "Testing..."},
    "ov_test_ok":       {"es": "Conectado · {n} modelos","en": "Connected · {n} models"},
    "ov_test_fail":     {"es": "Sin conexión al proveedor", "en": "No provider connection"},
    "ov_no_models":     {"es": "No hay modelos disponibles", "en": "No models available"},
    "ov_local_badge":   {"es": "🖥  LOCAL · nada sale de tu equipo",
                         "en": "🖥  LOCAL · nothing leaves your machine"},
    "ov_cloud_badge":   {"es": "☁  CLOUD · los datos se envían al proveedor",
                         "en": "☁  CLOUD · data is sent to the provider"},
    "rp_export_pdf":    {"es": "Exportar PDF",            "en": "Export PDF"},
    "rp_pdf_saved":     {"es": "PDF guardado",            "en": "PDF saved"},
    "rp_pdf_none":      {"es": "Nada que exportar",       "en": "Nothing to export"},
    "rp_pdf_title":     {"es": "Guardar reporte PDF",     "en": "Save report PDF"},
    "offline_banner":   {"es": "Backend offline · mostrando sesiones del disco (generación deshabilitada)",
                          "en": "Backend offline · showing sessions from disk (generation disabled)"},
    "theme_lbl":        {"es": "Tema:",                  "en": "Theme:"},
    "theme_light":      {"es": "Claro",                  "en": "Light"},
    "theme_dark":       {"es": "Oscuro",                 "en": "Dark"},
    # Capture target / smart capture
    "rec_target_lbl":   {"es": "Capturar:",              "en": "Capture:"},
    "rec_tgt_active":   {"es": "Monitor activo (auto)",  "en": "Active monitor (auto)"},
    "rec_tgt_all":      {"es": "Toda la pantalla (todos los monitores)",
                          "en": "Whole screen (all monitors)"},
    "rec_tgt_monitor":  {"es": "Monitor {n}",            "en": "Monitor {n}"},
    "rec_tgt_window":   {"es": "Ventana: {t}",           "en": "Window: {t}"},
    "rec_tgt_refresh":  {"es": "Actualizar lista de pantallas/ventanas",
                          "en": "Refresh screens/windows list"},
    "rec_smart_lbl":    {"es": "Captura inteligente (IA en vivo)",
                          "en": "Smart capture (live AI)"},
    "rec_smart_tip":    {"es": ("Un modelo de visión local observa la pantalla y guarda una captura\n"
                                "solo cuando detecta un cambio relevante (menos capturas, más útiles)."),
                          "en": ("A local vision model watches the screen and saves a screenshot\n"
                                 "only when it detects a meaningful change (fewer, more useful shots).")},
    "rec_smart_model":  {"es": "Modelo IA:",             "en": "AI model:"},
    # Additional test cases
    "rp_more_cases":    {"es": "+ Test cases",           "en": "+ Test cases"},
    "rp_more_tip":      {"es": ("Genera casos de prueba nuevos (bordes, negativos, límites)\n"
                                "que amplían el reporte sin duplicar los existentes.\n"
                                "Elige cuántos en la casilla de al lado."),
                          "en": ("Generate new test cases (edge, negative, boundary)\n"
                                 "extending the report without duplicating existing ones.\n"
                                 "Choose how many in the box next to it.")},
    "rp_more_count_tip":{"es": "Cuántos casos nuevos generar (1-20)",
                          "en": "How many new cases to generate (1-20)"},
    "rp_more_generating": {"es": "Generando {n} casos adicionales...",
                           "en": "Generating {n} additional cases..."},
    # Report editing
    "rp_edit":          {"es": "Editar",                 "en": "Edit"},
    "rp_edit_tip":      {"es": ("Edita el Markdown del reporte: corrige un estado, reescribe\n"
                                "un caso o añade notas. Las capturas se muestran como\n"
                                "marcadores [captura N] y se conservan al guardar."),
                          "en": ("Edit the report Markdown: fix a status, reword a case or\n"
                                 "add notes. Screenshots appear as [screenshot N] markers\n"
                                 "and are preserved on save.")},
    "rp_save":          {"es": "Guardar",                "en": "Save"},
    "rp_save_tip":      {"es": "Guardar los cambios en el reporte",
                          "en": "Save the changes to the report"},
    "rp_saved":         {"es": "Reporte guardado",       "en": "Report saved"},
    "rp_save_err":      {"es": "No se pudo guardar el reporte",
                          "en": "Could not save the report"},
    "rp_saving":        {"es": "Guardando...",           "en": "Saving..."},
    "rp_unsaved_t":     {"es": "Cambios sin guardar",    "en": "Unsaved changes"},
    "rp_unsaved_m":     {"es": "El reporte tiene cambios sin guardar. ¿Guardarlos?",
                          "en": "The report has unsaved changes. Save them?"},
    "rp_edit_none":     {"es": "Genera el reporte antes de editarlo.",
                          "en": "Generate the report before editing it."},
    # Playwright codegen
    "pw_chk":           {"es": "Script Playwright",      "en": "Playwright script"},
    "pw_chk_tip":       {"es": ("Genera código Playwright (TypeScript) desde la sesión grabada.\n"
                                "Determinista: usa los selectores capturados, sin IA."),
                          "en": ("Generate Playwright (TypeScript) code from the recorded session.\n"
                                 "Deterministic: uses the captured selectors, no AI.")},
    "pw_title":         {"es": "Script Playwright",      "en": "Playwright script"},
    "pw_save":          {"es": "Guardar .spec.ts",       "en": "Save .spec.ts"},
    "pw_saved":         {"es": "Script guardado",        "en": "Script saved"},
    "pw_err":           {"es": "Error generando el script", "en": "Error generating script"},
    # Navigation
    "nav_sessions":     {"es": "Mis sesiones",           "en": "My Sessions"},
    "nav_projects":     {"es": "Proyectos",              "en": "Projects"},
    "nav_scripts":      {"es": "Mis scripts",            "en": "My Scripts"},
    "nav_record":       {"es": "Grabar",                 "en": "Record"},
    # Projects view
    "pj_title":         {"es": "Proyectos",              "en": "Projects"},
    "pj_hint":          {"es": ("Cada proyecto agrupa sesiones y scripts, y guarda un "
                                "contexto que la IA usa en todas sus generaciones."),
                          "en": ("Each project groups sessions and scripts, and keeps a "
                                 "context the AI uses in all its generations.")},
    "pj_new":           {"es": "＋ Nuevo proyecto",       "en": "＋ New project"},
    "pj_new_title":     {"es": "Nuevo proyecto",          "en": "New project"},
    "pj_new_prompt":    {"es": "Nombre del proyecto:",    "en": "Project name:"},
    "pj_sessions_n":    {"es": "{n} sesiones",            "en": "{n} sessions"},
    "pj_scripts_n":     {"es": "{n} scripts",             "en": "{n} scripts"},
    "pj_has_ctx":       {"es": "● Con contexto",          "en": "● Has context"},
    "pj_no_ctx":        {"es": "○ Sin contexto",          "en": "○ No context"},
    "pj_edit_ctx":      {"es": "Contexto",                "en": "Context"},
    "pj_view_sessions": {"es": "Ver sesiones",            "en": "View sessions"},
    "pj_open_scripts":  {"es": "Scripts",                 "en": "Scripts"},
    "pj_rename":        {"es": "Renombrar",               "en": "Rename"},
    "pj_delete":        {"es": "Eliminar",                "en": "Delete"},
    "pj_empty":         {"es": ("Aún no hay proyectos. Asigna uno a una sesión "
                                "(Renombrar) o crea uno nuevo."),
                          "en": ("No projects yet. Assign one to a session (Rename) "
                                 "or create a new one.")},
    "pj_rename_title":  {"es": "Renombrar proyecto",      "en": "Rename project"},
    "pj_rename_prompt": {"es": "Nuevo nombre para «{p}»:", "en": "New name for “{p}”:"},
    "pj_rename_busy":   {"es": "Renombrando proyecto...",  "en": "Renaming project..."},
    "pj_del_title":     {"es": "Eliminar proyecto",       "en": "Delete project"},
    "pj_del_msg":       {"es": ("¿Eliminar el proyecto «{p}»?\n\nSus {n} sesiones quedarán "
                                "SIN proyecto (no se borran). El contexto se elimina y la "
                                "carpeta de scripts vacía se retira."),
                          "en": ("Delete project “{p}”?\n\nIts {n} sessions will become "
                                 "project-LESS (not deleted). The context is removed and the "
                                 "empty scripts folder is dropped.")},
    "pj_del_busy":      {"es": "Eliminando proyecto...",   "en": "Deleting project..."},
    # Session rename / project
    "rename_btn":       {"es": "  Renombrar",            "en": "  Rename"},
    "rename_title":     {"es": "Renombrar sesión",       "en": "Rename session"},
    "rename_name_lbl":  {"es": "Nombre:",                "en": "Name:"},
    "rename_proj_lbl":  {"es": "Proyecto:",              "en": "Project:"},
    "rename_name_ph":   {"es": "Ej: Login con credenciales inválidas",
                          "en": "e.g.: Login with invalid credentials"},
    "rename_proj_ph":   {"es": "Ej: Portal Clientes",    "en": "e.g.: Customer Portal"},
    "rename_save":      {"es": "Guardar",                "en": "Save"},
    "rename_cancel":    {"es": "Cancelar",               "en": "Cancel"},
    "rename_err":       {"es": "Error al renombrar",     "en": "Rename error"},
    "no_project":       {"es": "Sin proyecto",           "en": "No project"},
    "untitled":         {"es": "(sin nombre)",           "en": "(untitled)"},
    # Recorder project fields
    "rec_name_lbl":     {"es": "Nombre sesión:",         "en": "Session name:"},
    "rec_proj_lbl":     {"es": "Proyecto:",              "en": "Project:"},
    "rec_name_ph":      {"es": "Opcional",               "en": "Optional"},
    "rec_proj_ph":      {"es": "Opcional",               "en": "Optional"},
    # Scripts view
    "sc_title":         {"es": "Mis scripts",            "en": "My Scripts"},
    "sc_hint":          {"es": ("Los scripts Playwright generados se guardan aquí, agrupados por "
                                "proyecto. Selecciona uno y pulsa Ejecutar para abrir el navegador."),
                          "en": ("Generated Playwright scripts are saved here, grouped by project. "
                                 "Select one and press Run to open the browser.")},
    "sc_run":           {"es": "  Ejecutar",             "en": "  Run"},
    "sc_open":          {"es": "Abrir carpeta",          "en": "Open folder"},
    "sc_delete":        {"es": "Eliminar",               "en": "Delete"},
    "sc_refresh":       {"es": "Actualizar",             "en": "Refresh"},
    "sc_setup":         {"es": "Instalar Playwright",    "en": "Install Playwright"},
    "sc_empty":         {"es": ("Aún no hay scripts. Genera uno desde una sesión "
                                "(Resumen -> Script Playwright)."),
                          "en": ("No scripts yet. Generate one from a session "
                                 "(Overview -> Playwright script).")},
    "sc_running":       {"es": "Ejecutando...",          "en": "Running..."},
    "sc_done":          {"es": "Finalizado (codigo {c})", "en": "Finished (exit {c})"},
    "sc_pass":          {"es": "✅ Test superado",        "en": "✅ Test passed"},
    "sc_fail":          {"es": "❌ Test falló (código {c}) — revisa el log de abajo",
                          "en": "❌ Test failed (exit {c}) — check the log below"},
    "creds_missing_t":  {"es": "Faltan credenciales de test",
                          "en": "Missing test credentials"},
    "creds_missing_m":  {"es": ("Este script inicia sesión con QA_USERNAME / QA_PASSWORD, "
                                "pero aún no están configuradas.\n\nRellénalas ahora para "
                                "que el login funcione (se guardan solo en qa-scripts/.env)."),
                          "en": ("This script logs in with QA_USERNAME / QA_PASSWORD, "
                                 "but they are not configured yet.\n\nFill them now so the "
                                 "login works (stored only in qa-scripts/.env).")},
    "sc_run_err":       {"es": "No se pudo ejecutar",    "en": "Could not run"},
    "sc_need_setup_t":  {"es": "Falta instalar Playwright", "en": "Playwright not installed"},
    "sc_need_setup_m":  {"es": ("Para ejecutar scripts hay que instalar Playwright y su navegador "
                                "(una sola vez). Instalar ahora?\n\nSe ejecutara:\n"
                                "  npm install -D @playwright/test\n  npx playwright install chromium"),
                          "en": ("To run scripts, Playwright and its browser must be installed (once). "
                                 "Install now?\n\nWill run:\n"
                                 "  npm install -D @playwright/test\n  npx playwright install chromium")},
    "sc_setup_running": {"es": "Instalando Playwright... (puede tardar unos minutos)",
                          "en": "Installing Playwright... (this may take a few minutes)"},
    "sc_setup_done":    {"es": "Playwright instalado. Ya puedes ejecutar scripts.",
                          "en": "Playwright installed. You can now run scripts."},
    "sc_setup_fail":    {"es": "Fallo la instalacion",   "en": "Installation failed"},
    "sc_del_confirm":   {"es": "Eliminar este script?",  "en": "Delete this script?"},
    "sc_saved_to":      {"es": "Script guardado en Mis Scripts",
                          "en": "Script saved to My Scripts"},
    # Test credentials (qa-scripts/.env)
    "creds_btn":        {"es": "🔐 Credenciales de test",  "en": "🔐 Test credentials"},
    "creds_title":      {"es": "Credenciales de test — qa-scripts/.env",
                          "en": "Test credentials — qa-scripts/.env"},
    "creds_hint":       {"es": ("Los scripts generados leen estos valores al ejecutarse "
                                "(QA_BASE_URL, QA_USERNAME, QA_PASSWORD): así el login y la "
                                "URL funcionan sin escribir secretos en el código. Se guardan "
                                "SOLO en qa-scripts/.env — git-ignorado y nunca enviado a la IA."),
                          "en": ("Generated specs read these values at run time (QA_BASE_URL, "
                                 "QA_USERNAME, QA_PASSWORD): login and URL work without secrets "
                                 "in the code. Stored ONLY in qa-scripts/.env — git-ignored and "
                                 "never sent to the AI.")},
    "creds_url":        {"es": "URL base de la app:",      "en": "App base URL:"},
    "creds_user":       {"es": "Usuario / email:",         "en": "Username / email:"},
    "creds_pass":       {"es": "Contraseña:",              "en": "Password:"},
    "creds_show":       {"es": "Mostrar",                  "en": "Show"},
    "creds_saved":      {"es": "Credenciales guardadas en qa-scripts/.env",
                          "en": "Credentials saved to qa-scripts/.env"},
    # Project context
    "ctx_btn":          {"es": "Contexto del proyecto",  "en": "Project context"},
    "ctx_title":        {"es": "Contexto del proyecto — {p}",
                          "en": "Project context — {p}"},
    "ctx_hint":         {"es": ("Describe el proyecto para que la IA sea más precisa: qué es, "
                                "cómo funciona, roles, reglas de negocio, qué esperar. Este texto "
                                "se envía como contexto en TODAS las generaciones de este proyecto."),
                          "en": ("Describe the project so the AI is more accurate: what it is, how "
                                 "it works, roles, business rules, what to expect. This text is sent "
                                 "as context in ALL generations for this project.")},
    "ctx_ph":           {"es": "# Proyecto: ...\n\nQué es, cómo funciona, roles, reglas, qué esperar...",
                          "en": "# Project: ...\n\nWhat it is, how it works, roles, rules, what to expect..."},
    "ctx_save":         {"es": "Guardar contexto",        "en": "Save context"},
    "ctx_saved":        {"es": "Contexto guardado",       "en": "Context saved"},
    "ctx_err":          {"es": "Error con el contexto",   "en": "Context error"},
    "ctx_no_project_t": {"es": "Sesión sin proyecto",     "en": "Session has no project"},
    "ctx_no_project_m": {"es": ("Asigna un proyecto a esta sesión primero (botón Renombrar) "
                                "para poder editar su contexto."),
                          "en": ("Assign a project to this session first (Rename button) "
                                 "to edit its context.")},
    "ctx_add_report":   {"es": "➕ Añadir al contexto",   "en": "➕ Add to context"},
    "ctx_add_tip":      {"es": ("Añade este reporte al contexto del proyecto (ideal para el "
                                "análisis exploratorio: alimenta a la IA en futuras generaciones)."),
                          "en": ("Append this report to the project context (great for the "
                                 "exploratory analysis: feeds the AI in future generations).")},
    "ctx_added":        {"es": "Añadido al contexto del proyecto", "en": "Added to project context"},
}

# ── AI provider / model registry (mirrors backend _DEFAULT_MODEL) ────────────
_PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "models": [
            ("claude-sonnet-5",  "Claude Sonnet 5"),
            ("claude-opus-5",    "Claude Opus 5  (máxima calidad)"),
            ("claude-haiku-4-5", "Claude Haiku 4.5  (rapido)"),
        ],
    },
    "ollama": {
        "label": "🖥  Local (Ollama)",
        # Fallback list — replaced live by /providers/ollama/models when reachable.
        "models": [
            ("qwen2.5vl:7b",          "Qwen2.5-VL 7B  👁 visión  ★ recomendado"),
            ("minicpm-v4.5:8b",       "MiniCPM-V 4.5 8B  👁 visión  (mejor OCR)"),
            ("qwen3-vl:8b",           "Qwen3-VL 8B  👁 visión  (falla en tablas)"),
            ("llama3.2-vision:11b",   "Llama 3.2 Vision 11B"),
        ],
    },
    "ollama-cloud": {
        "label": "☁  Ollama Cloud",
        # Fallback list — replaced live by /providers/ollama-cloud/models once
        # OLLAMA_API_KEY is set. Vision models can read the screenshots.
        "models": [
            ("qwen3-vl:235b",      "Qwen3-VL 235B  👁 visión  ★ recomendado"),
            ("qwen3-vl:32b",       "Qwen3-VL 32B  👁 visión"),
            ("gpt-oss:120b",       "GPT-OSS 120B  (solo texto)"),
            ("deepseek-v3.1:671b", "DeepSeek V3.1 671B  (solo texto)"),
        ],
    },
    "gemini": {
        "label": "Google (Gemini)",
        # Fallback list — replaced live by /providers/gemini/models when the
        # backend has a GEMINI_API_KEY configured.
        "models": [
            ("gemini-2.5-flash", "Gemini 2.5 Flash  ★ recomendado"),
            ("gemini-2.5-pro",   "Gemini 2.5 Pro"),
        ],
    },
    "groq": {
        "label": "Groq  (gratis)",
        # Groq retiró los llama-3.2 vision "preview" — Llama 4 los sustituye.
        "models": [
            ("meta-llama/llama-4-scout-17b-16e-instruct",
             "Llama 4 Scout  👁 visión  ★ recomendado"),
            ("meta-llama/llama-4-maverick-17b-128e-instruct",
             "Llama 4 Maverick  👁 visión"),
            ("llama-3.3-70b-versatile",      "Llama 3.3 70B  (solo texto)"),
        ],
    },
}

# Providers whose installed/available models can be listed live via the
# backend (GET /providers/{id}/models).
_PROBEABLE = {"ollama", "gemini", "ollama-cloud"}

# Providers that run entirely on this machine (nothing leaves it). Everything
# else sends the session data (screenshots + steps) to a remote service — the UI
# flags that difference with a Local/Cloud badge next to the provider selector.
_LOCAL_PROVIDERS = {"ollama"}

# AI report sections the user can pick, in report order.
# (key, label_es, label_en, default_checked)  — key must match claude_gen.VALID_SECTIONS
_SECTIONS: list[tuple[str, str, str, bool]] = [
    ("summary",            "Resumen / Explicación",  "Summary / Explanation",  True),
    ("steps_to_reproduce", "Pasos para reproducir",  "Steps to reproduce",     True),
    ("exploratory",        "Testing exploratorio",   "Exploratory testing",    False),
    ("test_cases",         "Casos de prueba",        "Test cases",             True),
    ("test_plan",          "Plan de pruebas",        "Test plan",              False),
    ("bug_report",         "Reporte de bug",         "Bug report",             False),
    ("jira",               "Ticket Jira",            "Jira ticket",            False),
]

# Per-section visual metadata for the selection cards: glyph + one-line hint.
_SECTION_META: dict[str, tuple[str, str, str]] = {
    #  key:                (glyph, desc_es, desc_en)
    "summary":            ("📝", "Qué se probó y el resultado",   "What was tested and the outcome"),
    "steps_to_reproduce": ("🧭", "Lista numerada de pasos",       "Numbered list of steps"),
    "exploratory":        ("🔎", "Charter, riesgos, cobertura",   "Charter, risks, coverage"),
    "test_cases":         ("✅", "Pasos, esperado y obtenido",     "Steps, expected and actual"),
    "test_plan":          ("📋", "Acción / esperado / estado",     "Action / expected / status"),
    "bug_report":         ("🐛", "Severidad, repro, esperado",     "Severity, repro, expected"),
    "jira":               ("🎫", "Ticket listo para Jira",         "Jira-ready ticket"),
    "playwright":         ("🎭", "Script .spec.ts ejecutable",     "Runnable .spec.ts script"),
}

def _tr(key: str) -> str:
    return _TR.get(key, {}).get(_ui_lang, _TR.get(key, {}).get("es", key))

# Sidebar navigation entries: (i18n key, monochrome glyph). Order = page order.
_NAV_ITEMS: list[tuple[str, str]] = [
    ("nav_sessions", "▤"),
    ("nav_projects", "▦"),
    ("nav_scripts",  "‹/›"),
    ("nav_record",   "◉"),
]

# Project root (FullQA.ai/) relative to this file (FullQA.ai/desktop/ui.py)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Make agent modules importable
_AGENT_DIR = str(_PROJECT_ROOT / "agent")
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

# ── markdown -> HTML ─────────────────────────────────────────────────────────
try:
    import markdown as _md
    _CSS = (
        "<style>body{font-family:'Segoe UI',system-ui,sans-serif;line-height:1.6;"
        "font-size:13px;color:#1f2333;background:#ffffff}"
        "h1{color:#2563eb;border-bottom:2px solid #dbeafe;padding-bottom:4px}"
        "h2{color:#1e40af;margin-top:1em}h3{color:#1d4ed8;margin-top:.8em}"
        "code{background:#f1f5f9;padding:2px 5px;border-radius:3px}"
        "pre{background:#f5f5f5;padding:10px;border-radius:4px;overflow-x:auto}"
        "table{border-collapse:collapse}th{background:#eff6ff;color:#1e40af}"
        "td,th{border:1px solid #ddd;padding:5px 10px}"
        "img{max-width:100%;border:1px solid #e5e7eb;border-radius:6px;margin:6px 0}"
        "blockquote{color:#475569;border-left:3px solid #bfdbfe;padding-left:10px}</style>"
    )
    def _to_html(text: str) -> str:
        return _CSS + _md.markdown(text, extensions=["tables", "fenced_code", "nl2br"])
except ImportError:
    def _to_html(text: str) -> str:
        return (
            "<pre style='white-space:pre-wrap;font-family:monospace;font-size:12px'>"
            + html.escape(text) + "</pre>"
        )

# ── Theme palettes (indigo + deep slate — modern tech look) ──────────────────
_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#eef2f8", "surface": "#ffffff", "surface2": "#f6f8fc",
        "border": "#dde5f0", "border2": "#c3cfe2",
        "text": "#0c1428", "muted": "#5d6b85",
        "accent": "#4f46e5", "accent_h": "#4338ca", "accent_p": "#3730a3",
        "accent2": "#0891b2",
        "sel_bg": "#e0e7ff", "sel_fg": "#312e81",
        "header_bg": "#0d1322", "header_fg": "#f4f7ff",
        "header_accent": "#818cf8", "header_muted": "#93a1bd",
        "ok": "#059669", "bad": "#dc2626", "warn": "#d97706",
        "danger": "#dc2626", "danger_h": "#b91c1c",
        "banner_bg": "#fef3c7", "banner_fg": "#92400e", "banner_bd": "#fcd34d",
        "term_bg": "#0d1322", "term_fg": "#9fe8c3",
        "scrollbar": "#c3cfe2", "scrollbar_h": "#93a1bd",
    },
    "dark": {
        "bg": "#090f1e", "surface": "#101828", "surface2": "#0d1424",
        "border": "#1f2c47", "border2": "#2d3d60",
        "text": "#e4eaf6", "muted": "#8598b8",
        "accent": "#6366f1", "accent_h": "#818cf8", "accent_p": "#4f46e5",
        "accent2": "#22d3ee",
        "sel_bg": "#232f5c", "sel_fg": "#dfe6ff",
        "header_bg": "#060b16", "header_fg": "#eef2fb",
        "header_accent": "#818cf8", "header_muted": "#7c8db0",
        "ok": "#22c55e", "bad": "#ef4444", "warn": "#f59e0b",
        "danger": "#f87171", "danger_h": "#ef4444",
        "banner_bg": "#2a2410", "banner_fg": "#fbbf24", "banner_bd": "#4d3d12",
        "term_bg": "#060b16", "term_fg": "#8be9b6",
        "scrollbar": "#2d3d60", "scrollbar_h": "#41547e",
    },
}

# Light by default; never follow the system theme.
_theme = "light"

def _build_qss(p: dict[str, str]) -> str:
    return f"""
* {{ font-family: 'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif; }}
QWidget {{ background: {p['bg']}; color: {p['text']}; font-size: 13px; }}
QLabel, QCheckBox {{ background: transparent; }}
QToolTip {{
    background: {p['header_bg']}; color: {p['header_fg']};
    border: 1px solid {p['accent']}; border-radius: 6px; padding: 6px 10px; font-size: 12px;
}}

/* ── Header bar ─────────────────────────────────────────────── */
QFrame#Header {{ background: {p['header_bg']}; border: none; border-bottom: 2px solid {p['accent']}; }}
QFrame#Header QLabel {{ background: transparent; color: {p['header_fg']}; }}
QLabel#LogoMark  {{ color: {p['accent2']}; font-size: 20px; }}
QLabel#LogoText  {{ color: {p['header_fg']}; font-size: 18px; font-weight: 800; }}
QLabel#Tagline   {{ color: {p['header_muted']}; font-size: 11px; padding-top: 5px; }}
QFrame#Header QLabel#Muted {{ color: {p['header_muted']}; }}
QFrame#Header QComboBox {{
    background: rgba(255,255,255,0.08); color: {p['header_fg']};
    border: 1px solid rgba(255,255,255,0.18); border-radius: 7px; padding: 4px 8px;
    combobox-popup: 0;
}}
QFrame#Header QComboBox:hover {{ border-color: {p['header_accent']}; }}
QFrame#Header QComboBox QAbstractItemView {{
    background:{p['surface']}; color:{p['text']};
    border: 1px solid {p['border2']}; border-radius: 8px; padding: 4px;
    outline: none;
    selection-background-color:{p['sel_bg']}; selection-color:{p['sel_fg']};
}}
QFrame#Header QComboBox QAbstractItemView::item {{
    min-height: 26px; padding: 2px 8px; border-radius: 5px;
}}
QFrame#Header QPushButton {{
    background: rgba(255,255,255,0.10); color: {p['header_fg']};
    border: 1px solid rgba(255,255,255,0.22); border-radius: 7px; padding: 4px 14px;
}}
QFrame#Header QPushButton:hover {{ background: rgba(255,255,255,0.20); border-color: {p['header_accent']}; }}

/* Status pill */
QLabel#Pill {{
    border-radius: 12px; padding: 5px 14px; font-weight: 700; font-size: 12px;
    background: {p['muted']}; color: #ffffff;
}}
QLabel#Pill[state="ok"]   {{ background: {p['ok']}; }}
QLabel#Pill[state="bad"]  {{ background: {p['bad']}; }}
QLabel#Pill[state="warn"] {{ background: {p['warn']}; }}

/* ── Left navigation rail ───────────────────────────────────── */
QListWidget#Nav {{
    background: {p['surface2']}; border: 1px solid {p['border']};
    border-radius: 12px; padding: 8px 6px; outline: 0;
}}
QListWidget#Nav::item {{
    padding: 12px 12px; border-radius: 8px; margin: 3px 2px;
    color: {p['muted']}; font-size: 13px; font-weight: 600;
    border-left: 3px solid transparent;
}}
QListWidget#Nav::item:selected {{
    background: {p['sel_bg']}; color: {p['sel_fg']};
    border-left: 3px solid {p['accent']};
}}
QListWidget#Nav::item:hover:!selected {{ background: {p['surface']}; color: {p['text']}; }}

/* Offline banner */
QLabel#Banner {{
    background: {p['banner_bg']}; color: {p['banner_fg']}; padding: 7px 16px;
    border-bottom: 1px solid {p['banner_bd']}; font-weight: 600;
}}

/* ── Cards & titles ─────────────────────────────────────────── */
QFrame#Card {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; }}
QFrame#Card QLabel, QFrame#Card QCheckBox {{ background: transparent; }}
QLabel#PageTitle    {{ font-size: 18px; font-weight: 800; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 700; }}
QLabel#CardTitle    {{ font-size: 13px; font-weight: 700; }}
QLabel#CardKicker   {{ color: {p['muted']}; font-size: 10.5px; font-weight: 700; letter-spacing: 1px; }}
QLabel#Crumb        {{ color: {p['muted']}; font-size: 12px; }}
QLabel#CrumbStrong  {{ color: {p['text']}; font-size: 15px; font-weight: 800; }}

/* Stat chips (session metrics row) */
QFrame#StatChip {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 10px; }}
QLabel#StatValue {{ font-size: 17px; font-weight: 800; color: {p['accent']}; }}
QLabel#StatName  {{ color: {p['muted']}; font-size: 10px; font-weight: 700; letter-spacing: .6px; }}

/* Section selection cards (what to generate) */
QFrame#SectionCard {{
    background: {p['surface2']}; border: 1px solid {p['border2']}; border-radius: 10px;
}}
QFrame#SectionCard:hover {{ border-color: {p['accent_h']}; }}
QFrame#SectionCard[checked="true"] {{
    background: {p['sel_bg']}; border: 1px solid {p['accent']};
}}
QFrame#SectionCard QLabel#SecName {{ font-weight: 700; font-size: 12.5px; }}
QFrame#SectionCard[checked="true"] QLabel#SecName {{ color: {p['sel_fg']}; }}
QFrame#SectionCard QLabel#SecDesc {{ color: {p['muted']}; font-size: 10.5px; }}
QFrame#SectionCard QLabel#SecTick {{ color: {p['accent']}; font-size: 15px; font-weight: 800; }}

/* Session cards (list) */
QFrame#SessionCard {{ background: transparent; border-radius: 10px; }}
QLabel#Thumb {{
    background: {p['surface2']}; border: 1px solid {p['border']};
    border-radius: 7px; color: {p['muted']};
}}
QLabel#SessName {{ font-weight: 700; font-size: 12.5px; }}
QLabel#SessMeta {{ color: {p['muted']}; font-size: 10.5px; }}
QLabel#Badge {{
    color: #ffffff; font-size: 9px; font-weight: 800; border-radius: 7px; padding: 1px 6px;
}}
QLabel#Badge[kind="done"] {{ background: {p['ok']}; }}
QLabel#Badge[kind="generating"] {{ background: {p['warn']}; }}
QLabel#Badge[kind="error"] {{ background: {p['bad']}; }}
QLabel#Badge[kind="captured"] {{ background: {p['muted']}; }}

/* Group header row (projects) */
QLabel#GroupHeader {{ color: {p['muted']}; font-size: 11px; font-weight: 800; letter-spacing: .8px; }}

/* Timeline (events) */
QLabel#TlTime {{ color: {p['muted']}; font-size: 10.5px; font-family: Consolas, monospace; }}
QLabel#TlNode {{ font-size: 13px; }}
QLabel#TlText {{ font-size: 12.5px; }}
QLabel#TlWindow {{ color: {p['muted']}; font-size: 10.5px; }}
QFrame#TlLine {{ background: {p['border2']}; max-width: 2px; min-width: 2px; border: none; }}

/* Muted / tone / form labels + separators */
QLabel#Muted {{ color: {p['muted']}; }}
QLabel#Muted[tone="ok"]  {{ color: {p['ok']}; font-weight: 600; }}
QLabel#Muted[tone="bad"] {{ color: {p['bad']}; font-weight: 600; }}
QLabel#FormLabel {{ color: {p['text']}; font-weight: 600; }}
QFrame#Sep {{ border: none; border-top: 1px solid {p['border']}; max-height: 1px; }}

/* ── Buttons ────────────────────────────────────────────────── */
QPushButton {{
    background: {p['surface']}; color: {p['text']};
    border: 1px solid {p['border2']}; border-radius: 8px; padding: 6px 14px;
    font-weight: 600;
}}
QPushButton:hover  {{ border-color: {p['accent']}; color: {p['accent']}; }}
QPushButton:pressed{{ background: {p['sel_bg']}; color: {p['sel_fg']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['surface2']}; border-color:{p['border']}; }}
QPushButton#Accent {{ background: {p['accent']}; color: #ffffff; border: none; }}
QPushButton#Accent:hover   {{ background: {p['accent_h']}; color: #ffffff; }}
QPushButton#Accent:pressed {{ background: {p['accent_p']}; }}
QPushButton#Accent:disabled {{ background: {p['border2']}; color: {p['surface']}; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid transparent; color: {p['muted']}; }}
QPushButton#Ghost:hover   {{ color: {p['accent']}; background: {p['surface2']}; border-color: {p['border']}; }}
QPushButton#Ghost:pressed {{ background: {p['sel_bg']}; }}
QPushButton#Danger {{ background: transparent; color: {p['danger']}; border: 1px solid transparent; }}
QPushButton#Danger:hover   {{ border-color: {p['danger']}; color: {p['danger_h']}; }}
QPushButton#Danger:disabled {{ color: {p['muted']}; background: transparent; }}
QPushButton#RecordStart {{
    background: {p['ok']}; color: #ffffff; border: none; border-radius: 10px;
    font-size: 14px; font-weight: 700;
}}
QPushButton#RecordStart:hover {{ background: {p['accent']}; color: #ffffff; }}
QPushButton#RecordStart:disabled {{ background: {p['border2']}; color: {p['surface']}; }}
QPushButton#RecordStop {{
    background: {p['bad']}; color: #ffffff; border: none; border-radius: 10px;
    font-size: 14px; font-weight: 700;
}}
QPushButton#RecordStop:hover {{ background: {p['danger_h']}; color: #ffffff; }}
QPushButton#RecordStop:disabled {{ background: {p['border2']}; color: {p['surface']}; }}

/* ── Inputs ─────────────────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox {{
    background: {p['surface']}; border: 1px solid {p['border2']}; border-radius: 8px;
    padding: 6px 10px; selection-background-color: {p['sel_bg']}; selection-color: {p['sel_fg']};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {p['accent_h']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {p['accent']}; }}
QSpinBox {{ padding: 2px 2px 2px 6px; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background:{p['surface']}; color:{p['text']}; border: 1px solid {p['border2']};
    border-radius: 8px; padding: 4px; outline: none;
    selection-background-color:{p['sel_bg']}; selection-color:{p['sel_fg']};
}}
QComboBox QAbstractItemView::item {{
    min-height: 26px; padding: 2px 8px; border-radius: 5px;
}}

/* Checkboxes */
QCheckBox {{ color: {p['text']}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid {p['border2']}; background: {p['surface']};
}}
QCheckBox::indicator:hover   {{ border-color: {p['accent']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QCheckBox::indicator:checked:disabled {{ background: {p['border2']}; border-color: {p['border2']}; }}

/* ── Tabs (pill style) ──────────────────────────────────────── */
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 12px; background:{p['surface']}; top: 6px; }}
QTabBar::tab {{
    background: transparent; color: {p['muted']}; padding: 7px 18px;
    border-radius: 8px; margin: 0 4px 6px 0; font-weight: 600;
}}
QTabBar::tab:selected {{ background: {p['sel_bg']}; color: {p['sel_fg']}; }}
QTabBar::tab:hover:!selected {{ color: {p['text']}; background: {p['surface2']}; }}

/* ── Lists & trees ──────────────────────────────────────────── */
QListWidget {{
    background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px;
    outline: none; padding: 3px;
}}
QListWidget::item {{ padding: 8px 8px; border-radius: 8px; margin: 1px 0; color: {p['text']}; }}
QListWidget::item:selected {{ background: {p['sel_bg']}; color: {p['sel_fg']}; }}
QListWidget::item:hover:!selected {{ background: {p['surface2']}; }}
QTreeWidget {{
    background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px;
    outline: none; padding: 4px;
}}
QTreeWidget::item {{ padding: 7px 6px; border-radius: 8px; color: {p['text']}; }}
QTreeWidget::item:selected {{ background: {p['sel_bg']}; color: {p['sel_fg']}; }}
QTreeWidget::item:hover:!selected {{ background: {p['surface2']}; }}
QTreeWidget::branch {{ background: transparent; }}

/* ── Text views ─────────────────────────────────────────────── */
QTextBrowser {{ background:{p['surface']}; color:{p['text']}; border:1px solid {p['border']}; border-radius:12px; }}
/* Report view — always a light 'document', readable in both themes */
QTextBrowser#ReportView {{ background:#ffffff; color:#1f2333; border:1px solid {p['border']}; border-radius:12px; }}
QPlainTextEdit {{ background:{p['surface']}; color:{p['text']}; border:1px solid {p['border']}; border-radius:10px; padding: 4px; }}
QPlainTextEdit#Terminal {{
    background: {p['term_bg']}; color: {p['term_fg']};
    border: 1px solid {p['border2']}; border-radius: 10px; padding: 6px;
}}
QScrollArea {{ border: none; background: transparent; }}

/* ── Progress + scrollbars ──────────────────────────────────── */
QProgressBar {{ border:none; background:{p['border']}; border-radius:3px; max-height:6px; }}
QProgressBar::chunk {{ background:{p['accent']}; border-radius:3px; }}
QScrollBar:vertical {{ background:transparent; width:8px; margin:2px; }}
QScrollBar::handle:vertical {{ background:{p['scrollbar']}; border-radius:4px; min-height:24px; }}
QScrollBar::handle:vertical:hover {{ background:{p['scrollbar_h']}; }}
QScrollBar:horizontal {{ background:transparent; height:8px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:{p['scrollbar']}; border-radius:4px; min-width:24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QStatusBar {{ background:{p['surface2']}; color:{p['muted']}; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {p['sel_bg']}; }}
"""

def _make_card() -> tuple[QFrame, QVBoxLayout]:
    """A rounded surface 'card' plus its inner vertical layout, ready to fill."""
    card = QFrame()
    card.setObjectName("Card")
    inner = QVBoxLayout(card)
    inner.setContentsMargins(16, 14, 16, 14)
    inner.setSpacing(9)
    return card, inner


def _apply_theme(theme: str) -> None:
    """Apply a palette to the running QApplication."""
    global _theme
    _theme = theme if theme in _PALETTES else "light"
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(_build_qss(_PALETTES[_theme]))

# Print stylesheet for the PDF export (QTextDocument default stylesheet).
_PDF_CSS = (
    "body{font-family:'Segoe UI',system-ui,sans-serif;color:#1a1a2e;font-size:11pt}"
    "h1{color:#2563eb;font-size:20pt;border-bottom:2px solid #2563eb;padding-bottom:4px}"
    "h2{color:#1e40af;font-size:15pt;margin-top:18px}"
    "h3{color:#1d4ed8;font-size:12pt;margin-top:14px}"
    "table{border-collapse:collapse;width:100%;margin:8px 0}"
    "th{background:#eff6ff;color:#1e40af;text-align:left;padding:6px 10px;border:1px solid #bfdbfe}"
    "td{padding:6px 10px;border:1px solid #ddd;vertical-align:top}"
    "img{max-width:560px;margin:6px 0;border:1px solid #ccc}"
    "code{background:#f1f5f9;padding:1px 4px;border-radius:3px}"
    "blockquote{color:#475569;border-left:3px solid #bfdbfe;margin:6px 0;padding-left:10px}"
)

# ── API helpers ──────────────────────────────────────────────────────────────
def _get(path: str, timeout: int = 8):
    req = urllib.request.Request(API + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if "json" in r.headers.get("Content-Type", "") else body.decode()

def _post(path: str, data: dict, timeout: int = 10) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def _delete(path: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(
        API + path,
        headers={"Accept": "application/json"},
        method="DELETE",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def _put(path: str, data: dict, timeout: int = 10) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def _fmt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y  %H:%M")
    except Exception:
        return iso

# ── Local filesystem fallback (host has direct access to qa-sessions/) ───────
_SESSIONS_ROOT = Path(__file__).resolve().parent.parent / "qa-sessions"

def _find_local_session_dir(sid: str) -> Path | None:
    """Locate a session folder on disk: qa-sessions/YYYY-MM-DD/{uuid}/ or flat."""
    if not sid or "/" in sid or "\\" in sid or ".." in sid:
        return None
    if not _SESSIONS_ROOT.exists():
        return None
    flat = _SESSIONS_ROOT / sid
    if flat.exists():
        return flat
    for date_dir in _SESSIONS_ROOT.iterdir():
        if date_dir.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", date_dir.name):
            cand = date_dir / sid
            if cand.exists():
                return cand
    return None

def _scan_local_sessions() -> list[dict]:
    """Read every manifest.json under qa-sessions/ — used when the API is down."""
    out: list[dict] = []
    if not _SESSIONS_ROOT.exists():
        return out
    for date_dir in _SESSIONS_ROOT.iterdir():
        if not date_dir.is_dir():
            continue
        subdirs = [date_dir] if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_dir.name) \
            else [d for d in date_dir.iterdir() if d.is_dir()]
        for sd in subdirs:
            mp = sd / "manifest.json"
            if mp.exists():
                try:
                    m = json.loads(mp.read_text(encoding="utf-8"))
                    m.setdefault("status", "captured")
                    out.append(m)
                except Exception:
                    pass
    return out

def _local_events(sid: str) -> list[dict]:
    sd = _find_local_session_dir(sid)
    if not sd:
        return []
    ev_file = sd / "events.jsonl"
    if not ev_file.exists():
        return []
    events = []
    for line in ev_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events

def _local_screenshot(sid: str, fname: str) -> bytes | None:
    sd = _find_local_session_dir(sid)
    if not sd:
        return None
    img = sd / "screenshots" / fname
    if img.exists():
        return img.read_bytes()
    return None


def _local_first_screenshot(sid: str) -> bytes | None:
    """Return the bytes of a representative screenshot for a session (for the
    thumbnail). Picks the first PNG in the screenshots folder, sorted by name."""
    sd = _find_local_session_dir(sid)
    if not sd:
        return None
    shots_dir = sd / "screenshots"
    if not shots_dir.exists():
        return None
    pngs = sorted(p for p in shots_dir.glob("*.png"))
    if not pngs:
        return None
    try:
        return pngs[0].read_bytes()
    except Exception:
        return None


# ── Scripts storage (host-side; the desktop has direct filesystem access) ─────
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent / "qa-scripts"

# Minimal Playwright project scaffold written into qa-scripts/ on first save so
# that `npx playwright test --headed <file>` works. Headed + slowMo so the user
# can actually watch the automation run.
_PW_CONFIG = """\
import { defineConfig } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// Auto-generated by FullQA.ai. Runs headed and slowed down so you can watch.
//
// 1) Loads qa-scripts/.env into process.env (QA_BASE_URL, QA_USERNAME,
//    QA_PASSWORD, QA_LOGIN_URL) so specs get test credentials at run time —
//    no secrets are stored inside the .spec.ts files.
// 2) storageState: if you log in once with the 'setup' project, every spec
//    starts already authenticated. Create/refresh the saved session with:
//       npx playwright test --project=setup
const envFile = path.join(__dirname, '.env');
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, 'utf-8').split(/\\r?\\n/)) {
    if (line.trim().startsWith('#')) continue;
    const m = line.match(/^\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*=\\s*(.*)\\s*$/);
    if (m && process.env[m[1]] === undefined) {
      process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
    }
  }
}

const authFile = path.join(__dirname, '.auth', 'state.json');
const storageState = fs.existsSync(authFile) ? authFile : undefined;

const base = {
  headless: false,
  launchOptions: { slowMo: 350 },
  viewport: { width: 1280, height: 800 },
  // A step whose element never appears must fail fast with its name —
  // not hang until the whole-test timeout.
  actionTimeout: 20_000,
  screenshot: 'only-on-failure' as const,
};

export default defineConfig({
  testDir: '.',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  // Recorded flows replay MANY steps headed + slowMo: Playwright's default
  // 30s-per-test budget dies mid-flow (right after login on long sessions).
  timeout: 300_000,
  expect: { timeout: 10_000 },
  projects: [
    // Logs in with QA_* and saves the session. Run explicitly: --project=setup
    { name: 'setup', testMatch: /auth\\.setup\\.ts/, use: { ...base } },
    // Normal specs — reuse the saved login if it exists.
    { name: 'chromium', testMatch: /\\.spec\\.ts$/, use: { ...base, storageState } },
  ],
});
"""

_PW_ENV_EXAMPLE = """\
# FullQA.ai — credenciales/URL de test para los scripts Playwright generados.
# Copia este archivo a `.env` (git-ignorado) y rellena tus valores.
# Test credentials/URL for generated Playwright specs. Copy to `.env`.
QA_BASE_URL=
QA_USERNAME=
QA_PASSWORD=
# Optional: login page URL, if different from QA_BASE_URL.
QA_LOGIN_URL=
"""

# One-time login → saves auth to .auth/state.json so every spec starts
# authenticated. Useful when a recording began *after* login (no login steps).
_PW_AUTH_SETUP = """\
import { test as setup } from '@playwright/test';
import * as path from 'path';

// One-time login. Run with:  npx playwright test --project=setup
// It signs in with QA_USERNAME / QA_PASSWORD (from qa-scripts/.env) and saves
// the browser session to .auth/state.json — after that every *.spec.ts starts
// already authenticated (see storageState in playwright.config.ts).
//
// The locators below cover common login forms; ADJUST them to match your app.
const authFile = path.join(__dirname, '.auth', 'state.json');

setup('authenticate', async ({ page }) => {
  const url = process.env.QA_LOGIN_URL || process.env.QA_BASE_URL;
  if (!url) throw new Error('Set QA_BASE_URL (or QA_LOGIN_URL) in qa-scripts/.env');
  if (!process.env.QA_PASSWORD) throw new Error('Set QA_PASSWORD in qa-scripts/.env');

  await page.goto(url);

  // TODO: adjust to your login form if these do not match.
  await page.getByLabel(/e-?mail|correo|user|usuario/i).first()
    .fill(process.env.QA_USERNAME ?? '');
  await page.getByLabel(/password|contrase/i).first()
    .fill(process.env.QA_PASSWORD ?? '');
  await page.getByRole('button', { name: /sign ?in|log ?in|entrar|iniciar/i }).first()
    .click();

  // Give the app a moment to establish the session, then persist it.
  await page.waitForLoadState('networkidle');
  await page.context().storageState({ path: authFile });
});
"""

_PW_PACKAGE = """\
{
  "name": "qa-docai-scripts",
  "version": "1.0.0",
  "private": true,
  "description": "Playwright scripts generated by FullQA.ai"
}
"""


def _slug(text: str, fallback: str = "sin-proyecto") -> str:
    """Filesystem-safe slug for a project/name (keeps it human-readable)."""
    text = (text or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[^\w\s.\-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text).strip("-.")
    return text[:60] or fallback


def _ensure_scripts_scaffold() -> None:
    """Create qa-scripts/ with a Playwright config + package.json if missing."""
    _SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
    cfg = _SCRIPTS_ROOT / "playwright.config.ts"
    if not cfg.exists():
        cfg.write_text(_PW_CONFIG, encoding="utf-8")
    else:
        # Auto-upgrade an untouched FullQA.ai config that predates the current
        # features (.env loader, storageState/setup project). A config the user
        # customised (no FullQA.ai marker) is left alone.
        try:
            body = cfg.read_text(encoding="utf-8")
            outdated = "storageState" not in body or ".env" not in body
            if ("Auto-generated by FullQA.ai" in body
                    or "Auto-generated by QA-DocAI" in body) and outdated:
                cfg.write_text(_PW_CONFIG, encoding="utf-8")
        except Exception:
            pass
    setup = _SCRIPTS_ROOT / "auth.setup.ts"
    if not setup.exists():
        setup.write_text(_PW_AUTH_SETUP, encoding="utf-8")
    env_example = _SCRIPTS_ROOT / ".env.example"
    if not env_example.exists():
        env_example.write_text(_PW_ENV_EXAMPLE, encoding="utf-8")
    pkg = _SCRIPTS_ROOT / "package.json"
    if not pkg.exists():
        pkg.write_text(_PW_PACKAGE, encoding="utf-8")


# ── qa-scripts/.env helpers (test credentials for generated specs) ───────────
_ENV_KEYS = ("QA_BASE_URL", "QA_USERNAME", "QA_PASSWORD")


def _read_scripts_env() -> dict[str, str]:
    """Parse qa-scripts/.env into a dict (missing file → empty values)."""
    out = {k: "" for k in _ENV_KEYS}
    env = _SCRIPTS_ROOT / ".env"
    if not env.exists():
        return out
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k in out:
                out[k] = v.strip().strip("'\"")
    except Exception:
        pass
    return out


def _write_scripts_env(values: dict[str, str]) -> None:
    """Update QA_* keys in qa-scripts/.env, preserving any other content."""
    _ensure_scripts_scaffold()
    env = _SCRIPTS_ROOT / ".env"
    lines: list[str] = []
    if env.exists():
        try:
            lines = env.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
    remaining = dict(values)
    for i, line in enumerate(lines):
        if line.strip().startswith("#") or "=" not in line:
            continue
        k = line.partition("=")[0].strip()
        if k in remaining:
            lines[i] = f"{k}={remaining.pop(k)}"
    for k, v in remaining.items():
        lines.append(f"{k}={v}")
    env.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _save_script(code: str, project: str, name: str, sid: str) -> Path:
    """Write a generated Playwright spec into qa-scripts/<project>/<name>.spec.ts
    and return the path. Groups by project folder."""
    _ensure_scripts_scaffold()
    proj_dir = _SCRIPTS_ROOT / _slug(project, "sin-proyecto")
    proj_dir.mkdir(parents=True, exist_ok=True)
    base = _slug(name, sid[:8])
    path = proj_dir / f"{base}-{sid[:8]}.spec.ts"
    path.write_text(code, encoding="utf-8")
    return path


def _scan_scripts() -> dict[str, list[Path]]:
    """Return {project_folder_name: [spec paths]} for everything under qa-scripts/."""
    out: dict[str, list[Path]] = {}
    if not _SCRIPTS_ROOT.exists():
        return out
    for proj_dir in sorted(_SCRIPTS_ROOT.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name == "node_modules":
            continue
        specs = sorted(proj_dir.glob("*.spec.ts"))
        if specs:
            out[proj_dir.name] = specs
    return out


def _playwright_installed() -> bool:
    """True if @playwright/test is installed in qa-scripts/node_modules."""
    return (_SCRIPTS_ROOT / "node_modules" / "@playwright" / "test").exists()

# ── Thread base — auto-cleanup via finished signal ───────────────────────────
class _W(QThread):
    ok  = pyqtSignal(object)
    err = pyqtSignal(str)

    def start_tracked(self, store: list) -> "_W":
        """Start thread and add to store; remove on finish to allow GC."""
        store.append(self)
        self.finished.connect(lambda: store.remove(self) if self in store else None)
        self.start()
        return self

class HealthWorker(_W):
    def run(self):
        try:
            _get("/health", 3)
            self.ok.emit(True)
        except Exception:
            self.ok.emit(False)

class SessionsWorker(_W):
    def run(self):
        try:
            data = _get("/sessions")
            self.ok.emit({"sessions": data if isinstance(data, list) else [],
                          "offline": False})
        except Exception:
            # Backend down — fall back to scanning the disk directly so the
            # user's recordings always show up.
            self.ok.emit({"sessions": _scan_local_sessions(), "offline": True})

class ProviderModelsWorker(_W):
    """Fetch the live model list for a probeable provider (ollama/gemini)."""
    def __init__(self, provider: str, parent=None):
        super().__init__(parent)
        self.provider = provider
    def run(self):
        try:
            data = _get(f"/providers/{self.provider}/models", timeout=15)
            data["provider"] = self.provider
            self.ok.emit(data)
        except Exception as e:
            self.err.emit(str(e))

class DetailWorker(_W):
    def __init__(self, sid: str, parent=None):
        super().__init__(parent)
        self.sid = sid
    def run(self):
        try:
            self.ok.emit(_get(f"/sessions/{self.sid}"))
        except Exception as e:
            self.err.emit(str(e))

class EventsWorker(_W):
    def __init__(self, sid: str, parent=None):
        super().__init__(parent)
        self.sid = sid
    def run(self):
        try:
            d = _get(f"/sessions/{self.sid}/events")
            self.ok.emit(d.get("events", []) if isinstance(d, dict) else [])
        except Exception:
            self.ok.emit(_local_events(self.sid))   # disk fallback

class ReportWorker(_W):
    def __init__(self, sid: str, parent=None):
        super().__init__(parent)
        self.sid = sid
    def run(self):
        try:
            d = _get(f"/sessions/{self.sid}/report")
            self.ok.emit(d.get("report", "") if isinstance(d, dict) else str(d))
        except Exception as e:
            self.err.emit(str(e))

class SaveReportWorker(_W):
    """Write an edited report back to the API (PUT /sessions/{id}/report)."""
    def __init__(self, sid: str, markdown: str, parent=None):
        super().__init__(parent)
        self.sid, self.markdown = sid, markdown
    def run(self):
        try:
            # Reports carry base64 screenshots - allow for a slow write.
            self.ok.emit(_put(f"/sessions/{self.sid}/report",
                              {"report": self.markdown}, timeout=30))
        except Exception as e:
            self.err.emit(str(e))

class GenerateWorker(_W):
    def __init__(self, sid: str, lang: str = "es",
                 title: str = "", description: str = "",
                 sections: list[str] | None = None,
                 provider: str = "anthropic", model: str = "",
                 acceptance_criteria: str = "",
                 parent=None):
        super().__init__(parent)
        self.sid         = sid
        self.lang        = lang
        self.title       = title
        self.description = description
        self.sections    = sections or []
        self.provider    = provider
        self.model       = model
        self.acceptance_criteria = acceptance_criteria
    def run(self):
        try:
            payload = {
                "language":    self.lang,
                "title":       self.title,
                "description": self.description,
                "sections":    self.sections,
                "provider":    self.provider,
                "model":       self.model,
                "acceptance_criteria": self.acceptance_criteria,
            }
            self.ok.emit(_post(f"/sessions/{self.sid}/generate", payload))
        except Exception as e:
            self.err.emit(str(e))

class MoreCasesWorker(_W):
    """Ask the backend to append N new test cases to an existing report."""
    def __init__(self, sid: str, lang: str = "es", count: int = 5,
                 title: str = "", description: str = "",
                 provider: str = "anthropic", model: str = "",
                 acceptance_criteria: str = "", parent=None):
        super().__init__(parent)
        self.sid = sid
        self.payload = {
            "language": lang, "count": count, "title": title,
            "description": description, "provider": provider, "model": model,
            "acceptance_criteria": acceptance_criteria,
        }
    def run(self):
        try:
            self.ok.emit(_post(f"/sessions/{self.sid}/report/more-cases",
                               self.payload))
        except Exception as e:
            self.err.emit(str(e))


class PlaywrightWorker(_W):
    """Fetch the deterministic Playwright script for a session."""
    def __init__(self, sid: str, lang: str = "es", parent=None):
        super().__init__(parent)
        self.sid, self.lang = sid, lang
    def run(self):
        try:
            d = _get(f"/sessions/{self.sid}/playwright?language={self.lang}", timeout=20)
            self.ok.emit(d.get("code", "") if isinstance(d, dict) else str(d))
        except Exception as e:
            self.err.emit(str(e))


class ImageWorker(_W):
    def __init__(self, sid: str, fname: str, parent=None):
        super().__init__(parent)
        self.sid   = sid
        self.fname = fname
    def run(self):
        try:
            url = f"{API}/sessions/{self.sid}/screenshots/{self.fname}"
            with urllib.request.urlopen(url, timeout=10) as r:
                self.ok.emit((r.read(), self.fname))
        except Exception as e:
            data = _local_screenshot(self.sid, self.fname)   # disk fallback
            if data is not None:
                self.ok.emit((data, self.fname))
            else:
                self.err.emit(str(e))

class DeleteWorker(_W):
    def __init__(self, sid: str, parent=None):
        super().__init__(parent)
        self.sid = sid
    def run(self):
        try:
            _delete(f"/sessions/{self.sid}")
            self.ok.emit(self.sid)
        except Exception as e:
            self.err.emit(str(e))

def _persist_session_meta(sid: str, name: str, project: str) -> None:
    """Write a session's name/project to manifest.json (host access, offline-safe)
    and best-effort sync to the DB via the API."""
    try:
        sd = _find_local_session_dir(sid)
        if sd:
            mp = sd / "manifest.json"
            manifest = {}
            if mp.exists():
                try:
                    manifest = json.loads(mp.read_text(encoding="utf-8"))
                except Exception:
                    manifest = {}
            manifest["name"] = name or None
            manifest["project"] = project or None
            mp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception:
        pass
    try:
        _post(f"/sessions/{sid}/meta", {"name": name, "project": project})
    except Exception:
        pass


class MetaWorker(_W):
    """Persist a session's name + project. Tries the API first (updates the DB);
    always writes manifest.json on disk too so the change survives offline."""
    def __init__(self, sid: str, name: str, project: str, parent=None):
        super().__init__(parent)
        self.sid = sid
        self.name = name
        self.project = project
    def run(self):
        _persist_session_meta(self.sid, self.name, self.project)
        self.ok.emit(self.sid)


class ProjectsProbeWorker(_W):
    """Merge session-derived project names with the backend's known projects
    (so empty projects created via 'New project' still appear), and report which
    have a non-empty saved context. Emits {'names': [...], 'status': {name: bool}}."""
    def __init__(self, session_names: list[str], parent=None):
        super().__init__(parent)
        self._session_names = session_names
    def run(self):
        from urllib.parse import quote
        names = {n for n in self._session_names if n}
        try:
            d = _get("/projects", timeout=5)
            for n in (d.get("projects", []) if isinstance(d, dict) else []):
                if (n or "").strip():
                    names.add(n.strip())
        except Exception:
            pass
        ordered = sorted(names, key=str.lower)
        status: dict[str, bool] = {}
        for n in ordered:
            try:
                d = _get(f"/projects/{quote(n)}/context", timeout=4)
                status[n] = bool((d.get("context") or "").strip()) if isinstance(d, dict) else False
            except Exception:
                status[n] = False
        self.ok.emit({"names": ordered, "status": status})


class ProjectMutateWorker(_W):
    """Rename or delete a project client-side: reassign its sessions, move/clear
    its context, and rename/remove its scripts folder. Emits the new name ('' on
    delete)."""
    def __init__(self, action: str, old: str, new: str,
                 members: list[tuple[str, str]], parent=None):
        # members: list of (session_id, session_name) belonging to `old`.
        super().__init__(parent)
        self._action = action          # "rename" | "delete"
        self._old = old
        self._new = new
        self._members = members
    def run(self):
        from urllib.parse import quote
        target = self._new if self._action == "rename" else ""
        try:
            # 1) Reassign every session of the project (keeps each session name).
            for sid, sname in self._members:
                _persist_session_meta(sid, sname, target)
            # 2) Move/clear the per-project context.
            try:
                old_ctx = _get(f"/projects/{quote(self._old)}/context", timeout=5)
                ctx = old_ctx.get("context", "") if isinstance(old_ctx, dict) else ""
            except Exception:
                ctx = ""
            if self._action == "rename":
                if ctx.strip():
                    try:
                        _put(f"/projects/{quote(self._new)}/context", {"context": ctx})
                    except Exception:
                        pass
                try:
                    _put(f"/projects/{quote(self._old)}/context", {"context": ""})
                except Exception:
                    pass
            else:  # delete → clear context
                try:
                    _put(f"/projects/{quote(self._old)}/context", {"context": ""})
                except Exception:
                    pass
            # 3) Rename/remove the scripts folder (host filesystem).
            old_dir = _SCRIPTS_ROOT / _slug(self._old)
            if self._action == "rename":
                new_dir = _SCRIPTS_ROOT / _slug(self._new)
                if old_dir.exists() and old_dir != new_dir:
                    if new_dir.exists():
                        # Merge spec files into the existing target folder.
                        for spec in old_dir.glob("*.spec.ts"):
                            spec.rename(new_dir / spec.name)
                        try:
                            old_dir.rmdir()
                        except OSError:
                            pass
                    else:
                        old_dir.rename(new_dir)
            else:  # delete → drop the folder only if it has no specs left
                if old_dir.exists() and not any(old_dir.glob("*.spec.ts")):
                    import shutil
                    try:
                        shutil.rmtree(old_dir)
                    except Exception:
                        pass
            self.ok.emit(target)
        except Exception as e:
            self.err.emit(str(e))

class _StopRecordingWorker(_W):
    """Stops capture + audio and ingests the session — runs in background thread."""
    def __init__(self, capture, audio, session, watcher=None, parent=None):
        super().__init__(parent)
        self._capture = capture
        self._audio   = audio
        self._session = session
        self._watcher = watcher

    def run(self):
        try:
            if self._capture:
                self._capture.stop()
            if self._watcher:
                self._watcher.stop()
            if self._audio:
                self._audio.stop()   # blocks until WAV is saved and transcribed
            if self._session:
                self._session.end()
                sid = self._session.session_id
                try:
                    from uploader import ingest_session
                    ingest_session(sid)
                except Exception:
                    pass
                self.ok.emit(sid)
            else:
                self.ok.emit("")
        except Exception as e:
            self.err.emit(str(e))

# ── Image viewer dialog ──────────────────────────────────────────────────────
class ImageDialog(QDialog):
    def __init__(self, pixmap: QPixmap, caption: str, parent=None):
        super().__init__(parent)
        self._full_pixmap = pixmap
        self.setWindowTitle(caption)
        lay = QVBoxLayout(self)
        screen = QApplication.primaryScreen().availableGeometry()
        scaled = pixmap.scaled(
            int(screen.width() * 0.88), int(screen.height() * 0.82),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        lbl = QLabel()
        lbl.setPixmap(scaled)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)
        btns = QHBoxLayout()
        btns.addStretch()
        self._btn_copy = QPushButton(_tr("img_copy"))
        self._btn_copy.setFixedHeight(32)
        self._btn_copy.setFixedWidth(130)
        self._btn_copy.clicked.connect(self._copy)
        btns.addWidget(self._btn_copy)
        btn_close = QPushButton(_tr("img_close"))
        btn_close.setFixedHeight(32)
        btn_close.setFixedWidth(90)
        btn_close.clicked.connect(self.accept)
        btns.addWidget(btn_close)
        btns.addStretch()
        lay.addLayout(btns)
        self.adjustSize()

    def _copy(self):
        QApplication.clipboard().setImage(self._full_pixmap.toImage())
        self._btn_copy.setText(_tr("img_copied"))
        QTimer.singleShot(1500, lambda: self._btn_copy.setText(_tr("img_copy")))

# ── Custom QTextBrowser that renders embedded base64 images ──────────────────
class _ReportBrowser(QTextBrowser):
    """QTextBrowser subclass that:
    - Replaces data-URI <img> sources with img://N pseudo-URLs
    - Serves those bytes back via loadResource() so Qt renders them
    - Wraps each image in an <a href="img://N"> anchor
    - Emits image_clicked(raw_bytes, name) when user clicks an image
    """
    image_clicked = pyqtSignal(bytes, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._images: dict[str, bytes] = {}
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_anchor)

    def set_html_with_images(self, raw_html: str) -> None:
        self._images.clear()
        doc = self.document()
        idx = [0]

        def _replace(m: re.Match) -> str:
            key = f"img://{idx[0]}"
            attr = m.group(0)          # full: src="data:image/png;base64,XXXX"
            comma_pos = attr.index(",") + 1
            b64 = attr[comma_pos:-1]   # strip trailing "
            try:
                raw = base64.b64decode(b64)
            except Exception:
                return attr            # leave unchanged on decode error
            img = QImage()
            if not img.loadFromData(QByteArray(raw)):
                return attr            # undecodable image — leave as-is
            # Eagerly register a (display-sized) decoded image as a document
            # resource — the SAME mechanism the PDF export uses, which is
            # reliable across runtimes. The previous loadResource-only path
            # left images blank in some builds. Full-res bytes are kept for
            # the click-to-enlarge dialog.
            disp = img
            if img.width() > 820:
                disp = img.scaledToWidth(820, Qt.TransformationMode.SmoothTransformation)
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(key), disp)
            self._images[key] = raw
            idx[0] += 1
            return f'src="{key}"'

        processed = re.sub(
            r'src="data:image/[^;]+;base64,[^"]*"', _replace, raw_html
        )
        # Wrap each replaced img tag in a clickable anchor
        processed = re.sub(
            r'(<img\b[^>]*src="(img://\d+)"[^>]*>)',
            lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
            processed,
        )
        self.setHtml(processed)

    def loadResource(self, resource_type: int, url: QUrl) -> object:  # type: ignore[override]
        key = url.toString()
        if key in self._images:
            img = QImage()
            img.loadFromData(QByteArray(self._images[key]))
            return img
        return super().loadResource(resource_type, url)

    def _on_anchor(self, url: QUrl) -> None:
        key = url.toString()
        if key in self._images:
            self.image_clicked.emit(
                self._images[key],
                key.replace("img://", "screenshot_") + ".png",
            )

# ── Playwright code window ───────────────────────────────────────────────────
class CodeDialog(QDialog):
    """Separate window showing generated code with copy / save actions."""

    def __init__(self, code: str, sid: str, parent=None):
        super().__init__(parent)
        self._code = code
        self._sid = sid
        self.setWindowTitle(f"{_tr('pw_title')} — {sid[:8]}")
        self.resize(760, 560)
        lay = QVBoxLayout(self)

        self._view = QPlainTextEdit()
        self._view.setPlainText(code)
        self._view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._view.setFont(mono)
        lay.addWidget(self._view)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_copy = QPushButton(_tr("rp_copy"))
        btn_copy.clicked.connect(self._copy)
        btns.addWidget(btn_copy)
        self._btn_copy = btn_copy
        btn_save = QPushButton(_tr("pw_save"))
        btn_save.setObjectName("Accent")
        btn_save.clicked.connect(self._save)
        btns.addWidget(btn_save)
        btn_close = QPushButton(_tr("img_close"))
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_close)
        lay.addLayout(btns)

    def _copy(self):
        QApplication.clipboard().setText(self._code)
        self._btn_copy.setText(_tr("img_copied"))
        QTimer.singleShot(1500, lambda: self._btn_copy.setText(_tr("rp_copy")))

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, _tr("pw_save"), f"qa-{self._sid[:8]}.spec.ts",
            "Playwright spec (*.spec.ts);;TypeScript (*.ts)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._code)
            QMessageBox.information(self, _tr("pw_title"),
                                    f"{_tr('pw_saved')}:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, _tr("pw_title"), str(e))


# ── Rename / project dialog ──────────────────────────────────────────────────
class RenameDialog(QDialog):
    """Edit a session's friendly name and project. The project field is a
    free-text editable combo pre-filled with existing projects for convenience."""

    def __init__(self, name: str, project: str,
                 projects: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("rename_title"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self._name = QLineEdit(name)
        self._name.setPlaceholderText(_tr("rename_name_ph"))
        form.addRow(_tr("rename_name_lbl"), self._name)

        self._proj = QComboBox()
        self._proj.setEditable(True)
        self._proj.lineEdit().setPlaceholderText(_tr("rename_proj_ph"))
        seen = set()
        for p in projects:
            if p and p not in seen:
                seen.add(p)
                self._proj.addItem(p)
        self._proj.setCurrentText(project or "")
        form.addRow(_tr("rename_proj_lbl"), self._proj)
        lay.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText(_tr("rename_save"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(_tr("rename_cancel"))
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._name.setFocus()

    def values(self) -> tuple[str, str]:
        return self._name.text().strip(), self._proj.currentText().strip()


# ── Project context editor ───────────────────────────────────────────────────
class ProjectContextDialog(QDialog):
    """Editor for a project's free-form context markdown. This text is sent to
    the AI on every generation for the project, so it produces more accurate,
    project-aware results."""

    def __init__(self, project: str, parent=None):
        super().__init__(parent)
        self._project = project
        self.setWindowTitle(_tr("ctx_title").format(p=project))
        self.resize(680, 520)
        lay = QVBoxLayout(self)

        hint = QLabel(_tr("ctx_hint"))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText(_tr("ctx_ph"))
        mono = QFont("Consolas"); mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._edit.setFont(mono)
        lay.addWidget(self._edit, 1)

        # Load current context (small localhost payload; short timeout).
        try:
            from urllib.parse import quote
            data = _get(f"/projects/{quote(project)}/context", timeout=5)
            if isinstance(data, dict):
                self._edit.setPlainText(data.get("context", "") or "")
        except Exception:
            pass

        btns = QDialogButtonBox()
        self._btn_save = btns.addButton(_tr("ctx_save"),
                                        QDialogButtonBox.ButtonRole.AcceptRole)
        self._btn_save.setObjectName("Accent")
        btns.addButton(QDialogButtonBox.StandardButton.Cancel).setText(_tr("rename_cancel"))
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _save(self):
        from urllib.parse import quote
        try:
            _put(f"/projects/{quote(self._project)}/context",
                 {"context": self._edit.toPlainText()})
        except Exception as e:
            QMessageBox.critical(self, _tr("ctx_err"), str(e))
            return
        self.accept()


# ── Test credentials editor (qa-scripts/.env) ────────────────────────────────
class TestCredentialsDialog(QDialog):
    """Edit QA_BASE_URL / QA_USERNAME / QA_PASSWORD in qa-scripts/.env.
    Generated Playwright specs read them at run time, so secrets never live
    inside the .spec.ts files (and .env is git-ignored)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("creds_title"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)

        hint = QLabel(_tr("creds_hint"))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        form = QFormLayout()
        current = _read_scripts_env()

        self._url = QLineEdit(current.get("QA_BASE_URL", ""))
        self._url.setPlaceholderText("https://staging.miapp.com")
        form.addRow(_tr("creds_url"), self._url)

        self._user = QLineEdit(current.get("QA_USERNAME", ""))
        self._user.setPlaceholderText("qa.tester@miapp.com")
        form.addRow(_tr("creds_user"), self._user)

        pass_row = QHBoxLayout()
        self._pass = QLineEdit(current.get("QA_PASSWORD", ""))
        self._pass.setEchoMode(QLineEdit.EchoMode.Password)
        pass_row.addWidget(self._pass, 1)
        show = QCheckBox(_tr("creds_show"))
        show.toggled.connect(lambda on: self._pass.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        pass_row.addWidget(show)
        form.addRow(_tr("creds_pass"), pass_row)
        lay.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Save).setText(_tr("rename_save"))
        btns.button(QDialogButtonBox.StandardButton.Save).setObjectName("Accent")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(_tr("rename_cancel"))
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _save(self):
        try:
            _write_scripts_env({
                "QA_BASE_URL": self._url.text().strip(),
                "QA_USERNAME": self._user.text().strip(),
                "QA_PASSWORD": self._pass.text(),
            })
        except Exception as e:
            QMessageBox.critical(self, _tr("creds_title"), str(e))
            return
        self.accept()


# ── Session browser (grouped by project, with thumbnails) ────────────────────
class SessionBrowser(QWidget):
    """A richer session list: grouped by project, thumbnail per session, with
    rename + delete. Replaces the flat list on the 'My Sessions' page."""
    selected         = pyqtSignal(dict)
    delete_clicked   = pyqtSignal(dict)
    rename_requested = pyqtSignal(dict)

    _ICON_W, _ICON_H = 72, 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: list[dict] = []
        self._current: dict | None = None
        self._icon_cache: dict[str, QPixmap | None] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)

        self._title_lbl = QLabel(_tr("nav_sessions"))
        self._title_lbl.setObjectName("SectionTitle")
        lay.addWidget(self._title_lbl)

        self._search = QLineEdit()
        self._search.setPlaceholderText("⌕  " + _tr("search_ph"))
        self._search.textChanged.connect(lambda _q: self._rebuild())
        lay.addWidget(self._search)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setIndentation(10)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setUniformRowHeights(False)
        # The item widgets carry all content; never scroll horizontally and keep
        # the single column stretched to the viewport so cards can shrink cleanly.
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tree.header().setStretchLastSection(True)
        self._tree.currentItemChanged.connect(self._on_change)
        self._tree.itemDoubleClicked.connect(self._on_double)
        lay.addWidget(self._tree, 1)

        row = QHBoxLayout()
        self._btn_rename = QPushButton(_tr("rename_btn"))
        self._btn_rename.setEnabled(False)
        self._btn_rename.setFixedHeight(30)
        self._btn_rename.clicked.connect(self._on_rename)
        row.addWidget(self._btn_rename)

        self._btn_del = QPushButton(_tr("delete_btn"))
        self._btn_del.setObjectName("Danger")
        self._btn_del.setEnabled(False)
        self._btn_del.setFixedHeight(30)
        self._btn_del.clicked.connect(self._on_delete)
        row.addWidget(self._btn_del)
        lay.addLayout(row)

    # ── data ────────────────────────────────────────────────────────────
    def projects(self) -> list[str]:
        """Distinct project names currently in the list (for rename suggestions)."""
        out: list[str] = []
        seen = set()
        for s in self._sessions:
            p = (s.get("project") or "").strip()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return sorted(out)

    def update_sessions(self, sessions: list[dict]):
        ordered = sorted(
            sessions, key=lambda s: s.get("started_at", ""), reverse=True)
        # The 15 s auto-refresh usually returns exactly what we already show.
        # Rebuilding regardless clears the tree and re-creates every card, which
        # flashes the list and (via setCurrentItem) re-emits `selected` — that
        # is what made the Report tab reload itself on a loop. No change, no
        # rebuild.
        if ordered == self._sessions:
            return
        self._sessions = ordered
        self._rebuild()

    def filter_to(self, project: str):
        """Filter the list to a project's sessions (used from the Projects view)."""
        self._search.setText(project)

    def _thumb_pix(self, sid: str) -> QPixmap | None:
        if sid in self._icon_cache:
            return self._icon_cache[sid]
        pix = None
        data = _local_first_screenshot(sid)
        if data:
            img = QImage()
            if img.loadFromData(QByteArray(data)):
                pix = QPixmap.fromImage(img).scaled(
                    self._ICON_W, self._ICON_H,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                # Crop to exact tile size for a clean edge.
                pix = pix.copy(0, 0, self._ICON_W, self._ICON_H)
        self._icon_cache[sid] = pix
        return pix

    def _card_widget(self, s: dict) -> QWidget:
        """Rich session row: thumbnail · (name / date+badge). Built to survive a
        narrow sidebar: the name elides, nothing forces the row wider."""
        sid    = s.get("session_id", "")
        name   = (s.get("name") or "").strip() or _tr("untitled")
        status = s.get("status", "captured")
        # Parent to the tree from the start. A parentless QFrame is a potential
        # top-level window: while the card is built (before setItemWidget
        # reparents it) it can flash on screen for a frame — and with a
        # thumbnail pixmap set it materialises as a titled window showing that
        # screenshot. Rebuilding the list = one flash per card.
        card = QFrame(self._tree)
        card.setObjectName("SessionCard")
        h = QHBoxLayout(card)
        h.setContentsMargins(6, 5, 6, 5)
        h.setSpacing(9)

        thumb = QLabel()
        thumb.setObjectName("Thumb")
        thumb.setFixedSize(self._ICON_W, self._ICON_H)
        pix = self._thumb_pix(sid)
        if pix is not None:
            thumb.setPixmap(pix)   # already scaled+cropped to the tile size
        else:
            thumb.setText("—")
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(thumb, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(3)
        col.setContentsMargins(0, 0, 0, 0)

        nm = QLabel(name)
        nm.setObjectName("SessName")
        nm.setWordWrap(False)
        # Let the layout shrink the label below its text width (so a long name
        # never pushes the badge off-screen or over the thumbnail); the full
        # name lives in the tooltip.
        nm.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        col.addWidget(nm)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta = QLabel(_fmt(s.get("started_at")))
        meta.setObjectName("SessMeta")
        meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        meta_row.addWidget(meta, 1)

        badge_txt = {"done": "LISTO", "generating": "···", "error": "ERROR",
                     "captured": "NUEVO"}.get(status, status.upper()[:6])
        if _ui_lang == "en":
            badge_txt = {"LISTO": "DONE", "NUEVO": "NEW"}.get(badge_txt, badge_txt)
        badge = QLabel(badge_txt)
        badge.setObjectName("Badge")
        badge.setProperty("kind", status)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meta_row.addWidget(badge, 0)
        col.addLayout(meta_row)

        h.addLayout(col, 1)
        card.setToolTip(
            f"{name}\n{_fmt(s.get('started_at'))}\n"
            f"{s.get('event_count', 0)} eventos · {s.get('screenshot_count', 0)} capturas"
        )
        return card

    def _rebuild(self):
        q = self._search.text().lower().strip()
        prev_sid = (self._current or {}).get("session_id", "")
        self._tree.clear()

        # Group sessions by project (untitled project → "Sin proyecto").
        groups: dict[str, list[dict]] = {}
        for s in self._sessions:
            sid = s.get("session_id", "")
            name = (s.get("name") or "").strip()
            proj = (s.get("project") or "").strip()
            hay = " ".join([sid, s.get("started_at", ""), name, proj]).lower()
            if q and q not in hay:
                continue
            groups.setdefault(proj or _tr("no_project"), []).append(s)

        to_select = None
        for proj in sorted(groups, key=lambda p: (p == _tr("no_project"), p.lower())):
            items = groups[proj]
            top = QTreeWidgetItem([f"{proj.upper()}   ·   {len(items)}"])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)   # header: not selectable
            top.setData(0, Qt.ItemDataRole.UserRole + 1, "header")
            f = top.font(0); f.setBold(True); f.setPointSize(max(8, f.pointSize() - 1))
            top.setFont(0, f)
            self._tree.addTopLevelItem(top)
            top.setExpanded(True)
            for s in items:
                sid = s.get("session_id", "")
                child = QTreeWidgetItem()
                child.setData(0, Qt.ItemDataRole.UserRole, s)
                child.setSizeHint(0, QSize(0, self._ICON_H + 12))
                top.addChild(child)
                self._tree.setItemWidget(child, 0, self._card_widget(s))
                if sid and sid == prev_sid:
                    to_select = child

        if to_select is not None:
            # Restoring the selection after a rebuild is bookkeeping, not a user
            # action: emitting `selected` here would tell the DetailPanel to
            # reload a session it is already showing.
            blocked = self._tree.blockSignals(True)
            self._tree.setCurrentItem(to_select)
            self._tree.blockSignals(blocked)
            data = to_select.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                self._current = data
                self._btn_del.setEnabled(True)
                self._btn_rename.setEnabled(True)

    # ── events ──────────────────────────────────────────────────────────
    def _on_change(self, item: QTreeWidgetItem | None, _prev=None):
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if isinstance(data, dict):
            self._current = data
            self._btn_del.setEnabled(True)
            self._btn_rename.setEnabled(True)
            self.selected.emit(data)
        else:
            self._current = None
            self._btn_del.setEnabled(False)
            self._btn_rename.setEnabled(False)

    def _on_double(self, item: QTreeWidgetItem, _col: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.rename_requested.emit(data)

    def _on_rename(self):
        if self._current:
            self.rename_requested.emit(self._current)

    def _on_delete(self):
        if self._current:
            self.delete_clicked.emit(self._current)

    def retranslate(self):
        self._title_lbl.setText(_tr("nav_sessions"))
        self._search.setPlaceholderText("⌕  " + _tr("search_ph"))
        self._btn_rename.setText(_tr("rename_btn"))
        self._btn_del.setText(_tr("delete_btn"))
        self._rebuild()


# ── Recorder panel ───────────────────────────────────────────────────────────
class RecorderPanel(QWidget):
    """Controls for starting and stopping a new recording session from the UI."""
    session_saved = pyqtSignal(str)   # emits session_id after save + ingest
    # Emitted from the weblistener's server thread; Qt delivers them queued on
    # the GUI thread, so the browser extension can start/stop recordings.
    _remote_start = pyqtSignal(dict)
    _remote_stop  = pyqtSignal()

    def __init__(self, store: list, parent=None):
        super().__init__(parent)
        self._store        = store
        self._session      = None
        self._capture      = None
        self._audio        = None
        self._watcher      = None
        self._is_recording = False
        self._cd_val       = 0
        self._cd_timer     = QTimer(self)
        self._cd_timer.timeout.connect(self._tick)

        # App-lifetime local endpoint for the browser extension: receives web
        # events while recording AND lets the extension start/stop recordings.
        self._remote_start.connect(self._on_remote_start)
        self._remote_stop.connect(self._on_remote_stop)
        self._weblistener = None
        try:
            from weblistener import WebEventListener
            self._weblistener = WebEventListener(
                on_start=lambda opts: self._remote_start.emit(opts or {}),
                on_stop=lambda: self._remote_stop.emit(),
            )
            if not self._weblistener.start():
                self._weblistener = None      # port busy — extension disabled
        except Exception:
            self._weblistener = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(640)
        outer.addStretch(1)
        outer.addWidget(card, 4, Qt.AlignmentFlag.AlignTop)
        outer.addStretch(1)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(10)

        self._page_title = QLabel("◉  " + _tr("nav_record"))
        self._page_title.setObjectName("PageTitle")
        lay.addWidget(self._page_title)

        # Session name + project (optional; used to organise sessions & scripts)
        row_name = QHBoxLayout()
        self._rec_name_lbl = QLabel(_tr("rec_name_lbl"))
        row_name.addWidget(self._rec_name_lbl)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(_tr("rec_name_ph"))
        row_name.addWidget(self._name_edit, 1)
        lay.addLayout(row_name)

        row_proj = QHBoxLayout()
        self._rec_proj_lbl = QLabel(_tr("rec_proj_lbl"))
        row_proj.addWidget(self._rec_proj_lbl)
        # Editable combo: pick an existing project or type a new one (which
        # creates it). Populated by MainWindow via set_projects().
        self._proj_edit = QComboBox()
        self._proj_edit.setEditable(True)
        self._proj_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._proj_edit.lineEdit().setPlaceholderText(_tr("rec_proj_ph"))
        row_proj.addWidget(self._proj_edit, 1)
        lay.addLayout(row_proj)

        # Language selector
        row_lang = QHBoxLayout()
        self._rec_lang_lbl = QLabel(_tr("rec_lang_lbl"))
        row_lang.addWidget(self._rec_lang_lbl)
        self._lang_cb = QComboBox()
        self._lang_cb.addItem("Espanol", userData="es")
        self._lang_cb.addItem("English", userData="en")
        row_lang.addWidget(self._lang_cb, 1)
        lay.addLayout(row_lang)

        # Microphone selector
        row_mic = QHBoxLayout()
        self._rec_mic_lbl = QLabel(_tr("rec_mic_lbl"))
        row_mic.addWidget(self._rec_mic_lbl)
        self._mic_cb = QComboBox()
        self._mic_cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._populate_mics()
        row_mic.addWidget(self._mic_cb, 1)
        self._btn_ref_mic = QPushButton("R")
        self._btn_ref_mic.setFixedSize(26, 26)
        self._btn_ref_mic.setToolTip(_tr("rec_refresh_tip"))
        self._btn_ref_mic.clicked.connect(self._populate_mics)
        row_mic.addWidget(self._btn_ref_mic)
        lay.addLayout(row_mic)

        # Capture target: whole screen / a monitor / a specific window
        row_tgt = QHBoxLayout()
        self._tgt_lbl = QLabel(_tr("rec_target_lbl"))
        row_tgt.addWidget(self._tgt_lbl)
        self._tgt_cb = QComboBox()
        self._tgt_cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row_tgt.addWidget(self._tgt_cb, 1)
        self._btn_ref_tgt = QPushButton("R")
        self._btn_ref_tgt.setFixedSize(26, 26)
        self._btn_ref_tgt.setToolTip(_tr("rec_tgt_refresh"))
        self._btn_ref_tgt.clicked.connect(self._populate_targets)
        row_tgt.addWidget(self._btn_ref_tgt)
        lay.addLayout(row_tgt)
        self._populate_targets()

        # Smart capture: a local vision model watches the screen and saves a
        # shot only on meaningful changes (opt-in — uses the GPU while active).
        self._smart_chk = QCheckBox(_tr("rec_smart_lbl"))
        self._smart_chk.setToolTip(_tr("rec_smart_tip"))
        self._smart_chk.toggled.connect(self._on_smart_toggle)
        lay.addWidget(self._smart_chk)

        row_sm = QHBoxLayout()
        self._smart_model_lbl = QLabel(_tr("rec_smart_model"))
        row_sm.addWidget(self._smart_model_lbl)
        self._smart_model_cb = QComboBox()
        self._smart_model_cb.setEditable(True)
        self._smart_model_cb.addItem("qwen2.5vl:7b")
        self._smart_model_cb.addItem("qwen3-vl:8b")
        self._smart_model_cb.addItem("llama3.2-vision:11b")
        row_sm.addWidget(self._smart_model_cb, 1)
        lay.addLayout(row_sm)
        self._smart_row_widgets = (self._smart_model_lbl, self._smart_model_cb)
        self._on_smart_toggle(False)

        # Countdown label (big number, hidden when not counting)
        self._cd_lbl = QLabel("")
        self._cd_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cd_lbl.setFont(QFont("", 72, QFont.Weight.Bold))
        self._cd_lbl.setStyleSheet("color: #e67e22")
        self._cd_lbl.setFixedHeight(110)
        self._cd_lbl.setVisible(False)
        lay.addWidget(self._cd_lbl)

        # Start button
        self._btn_start = QPushButton("●  " + _tr("rec_start"))
        self._btn_start.setObjectName("RecordStart")
        self._btn_start.setFixedHeight(46)
        self._btn_start.clicked.connect(self._start_clicked)
        lay.addWidget(self._btn_start)

        # Stop button
        self._btn_stop = QPushButton("■  " + _tr("rec_stop"))
        self._btn_stop.setObjectName("RecordStop")
        self._btn_stop.setFixedHeight(46)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_clicked)
        lay.addWidget(self._btn_stop)

        # Status label
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setContentsMargins(0, 6, 0, 0)
        lay.addWidget(self._status)

        lay.addStretch()

    def set_projects(self, projects: list[str]):
        """Populate the project combo with existing projects (keeps what the
        user has typed so far)."""
        current = self._proj_edit.currentText()
        self._proj_edit.blockSignals(True)
        self._proj_edit.clear()
        self._proj_edit.addItems(projects)
        self._proj_edit.setCurrentText(current)
        self._proj_edit.blockSignals(False)

    def retranslate(self):
        self._page_title.setText("◉  " + _tr("nav_record"))
        self._rec_name_lbl.setText(_tr("rec_name_lbl"))
        self._name_edit.setPlaceholderText(_tr("rec_name_ph"))
        self._rec_proj_lbl.setText(_tr("rec_proj_lbl"))
        self._proj_edit.lineEdit().setPlaceholderText(_tr("rec_proj_ph"))
        self._rec_lang_lbl.setText(_tr("rec_lang_lbl"))
        self._rec_mic_lbl.setText(_tr("rec_mic_lbl"))
        self._btn_ref_mic.setToolTip(_tr("rec_refresh_tip"))
        self._tgt_lbl.setText(_tr("rec_target_lbl"))
        self._btn_ref_tgt.setToolTip(_tr("rec_tgt_refresh"))
        self._smart_chk.setText(_tr("rec_smart_lbl"))
        self._smart_chk.setToolTip(_tr("rec_smart_tip"))
        self._smart_model_lbl.setText(_tr("rec_smart_model"))
        self._btn_start.setText("●  " + _tr("rec_start"))
        self._btn_stop.setText("■  " + _tr("rec_stop"))
        if self._tgt_cb.count() >= 2:
            self._tgt_cb.setItemText(0, _tr("rec_tgt_active"))
            self._tgt_cb.setItemText(1, _tr("rec_tgt_all"))
        for i in range(self._mic_cb.count()):
            if self._mic_cb.itemData(i) is None:
                self._mic_cb.setItemText(i, _tr("rec_no_audio"))
                break

    def _populate_mics(self):
        """Refresh microphone list from sounddevice."""
        current_data = self._mic_cb.currentData()
        self._mic_cb.clear()
        self._mic_cb.addItem(_tr("rec_no_audio"), userData=None)
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0:
                    self._mic_cb.addItem(d["name"], userData=i)
        except Exception:
            pass
        # Restore previous selection
        for idx in range(self._mic_cb.count()):
            if self._mic_cb.itemData(idx) == current_data:
                self._mic_cb.setCurrentIndex(idx)
                break

    def _populate_targets(self):
        """Refresh the capture-target list (monitors + windows)."""
        prev = self._tgt_cb.currentData() if self._tgt_cb.count() else None
        self._tgt_cb.clear()
        self._tgt_cb.addItem(_tr("rec_tgt_active"), userData={"kind": "active"})
        self._tgt_cb.addItem(_tr("rec_tgt_all"),    userData={"kind": "all"})
        try:
            import screens
            for m in screens.list_monitors():
                lbl = _tr("rec_tgt_monitor").format(n=m["index"])
                lbl += f'  ({m["width"]}x{m["height"]})' + ("  ★" if m["primary"] else "")
                self._tgt_cb.addItem(lbl, userData={"kind": "monitor", "index": m["index"]})
            for w in screens.list_windows():
                title = w["title"]
                short = (title[:38] + "…") if len(title) > 39 else title
                self._tgt_cb.addItem(_tr("rec_tgt_window").format(t=short),
                                     userData={"kind": "window", "hwnd": w["hwnd"], "title": title})
        except Exception:
            pass
        if prev is not None:
            for i in range(self._tgt_cb.count()):
                if self._tgt_cb.itemData(i) == prev:
                    self._tgt_cb.setCurrentIndex(i)
                    break

    def _on_smart_toggle(self, checked: bool):
        for w in getattr(self, "_smart_row_widgets", ()):
            w.setVisible(bool(checked))

    # ── Remote control (browser extension via weblistener /control) ──────
    def _on_remote_start(self, opts: dict):
        """Apply the options chosen in the extension popup and start."""
        if self._is_recording or not self._btn_start.isEnabled():
            return
        idx = self._lang_cb.findData(opts.get("lang"))
        if idx >= 0:
            self._lang_cb.setCurrentIndex(idx)
        kind = opts.get("target")
        if kind in ("active", "all"):
            for i in range(self._tgt_cb.count()):
                data = self._tgt_cb.itemData(i)
                if isinstance(data, dict) and data.get("kind") == kind:
                    self._tgt_cb.setCurrentIndex(i)
                    break
        self._smart_chk.setChecked(bool(opts.get("smart")))
        if opts.get("model"):
            self._smart_model_cb.setCurrentText(str(opts["model"])[:80])
        if opts.get("mic"):
            for i in range(self._mic_cb.count()):     # first real microphone
                if self._mic_cb.itemData(i) is not None:
                    self._mic_cb.setCurrentIndex(i)
                    break
        else:
            self._mic_cb.setCurrentIndex(0)           # "no audio" entry
        self._start_clicked()

    def _on_remote_stop(self):
        if self._is_recording:
            self._stop_clicked()

    # ── Countdown ─────────────────────────────────────────────────────────
    def _start_clicked(self):
        self._btn_start.setEnabled(False)
        self._lang_cb.setEnabled(False)
        self._mic_cb.setEnabled(False)
        self._status.setText("")
        self._status.setStyleSheet("")
        self._cd_val = 3
        self._cd_lbl.setText("3")
        self._cd_lbl.setStyleSheet("color: #e67e22")
        self._cd_lbl.setVisible(True)
        self._cd_timer.start(1000)

    def _tick(self):
        self._cd_val -= 1
        if self._cd_val > 0:
            self._cd_lbl.setText(str(self._cd_val))
        else:
            self._cd_timer.stop()
            self._cd_lbl.setText("GO")
            self._cd_lbl.setStyleSheet("color: #27ae60")
            QTimer.singleShot(400, self._start_recording)

    # ── Recording start ────────────────────────────────────────────────────
    def _start_recording(self):
        self._cd_lbl.setVisible(False)
        try:
            from session import Session
            from capture import EventCapture
        except ImportError as e:
            self._recording_error(f"Import error (pynput/mss): {e}")
            return

        lang          = self._lang_cb.currentData() or "es"
        mic_device    = self._mic_cb.currentData()   # None = no audio
        audio_enabled = mic_device is not None
        target        = self._tgt_cb.currentData() or {"kind": "active"}
        smart         = self._smart_chk.isChecked()

        self._session = Session(language=lang, audio_enabled=audio_enabled)
        # Clicks/typing ALWAYS capture (deduplicated). With smart capture on,
        # the watcher adds extra shots of settled states and SHARES the dedup
        # fingerprint with the event capture, so each distinct screen state is
        # saved exactly once no matter who saw it first.
        self._audio   = None
        self._watcher = None
        shared_dedup  = None

        if smart:
            try:
                import screens as _scr
                from watcher import SmartCaptureWatcher
                shared_dedup = _scr.FrameDedup()
                self._watcher = SmartCaptureWatcher(
                    self._session, target=target,
                    model=self._smart_model_cb.currentText().strip() or "qwen2.5vl:7b",
                    shared_dedup=shared_dedup,
                )
            except Exception as e:
                self._watcher = None
                shared_dedup = None
                self._status.setText(f"IA off: {e}")

        self._capture = EventCapture(self._session, target=target,
                                     shared_dedup=shared_dedup)

        # Route browser-extension events into this session (listener runs for
        # the whole app lifetime; without a session it discards everything).
        if self._weblistener is not None:
            self._weblistener.attach(self._session)

        if audio_enabled:
            try:
                from audio import AudioRecorder
                self._audio = AudioRecorder(
                    self._session, language=lang, device=mic_device
                )
            except Exception as e:
                self._audio = None
                self._status.setText(f"{_tr('rec_audio_off')}{e}")

        self._capture.start()
        if self._watcher:
            self._watcher.start()
        if self._audio:
            self._audio.start()

        self._is_recording = True
        self._btn_stop.setEnabled(True)
        self._status.setStyleSheet("color: #e74c3c; font-weight: bold")
        self._status.setText(f"{_tr('rec_recording')}\n{self._session.session_id[:30]}...")

    # ── Recording stop ─────────────────────────────────────────────────────
    def _stop_clicked(self):
        if not self._is_recording:
            return
        self._is_recording = False
        self._btn_stop.setEnabled(False)
        self._status.setStyleSheet("color: #888")
        self._status.setText(_tr("rec_saving"))

        if self._weblistener is not None:
            self._weblistener.detach()   # stop routing web events immediately
        w = _StopRecordingWorker(self._capture, self._audio, self._session,
                                 self._watcher)
        w.ok.connect(self._on_stopped)
        w.err.connect(self._recording_error)
        w.start_tracked(self._store)
        self._capture = None
        self._audio   = None
        self._session = None
        self._watcher = None

    def _on_stopped(self, session_id: str):
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._lang_cb.setEnabled(True)
        self._mic_cb.setEnabled(True)
        self._status.setStyleSheet("color: #27ae60; font-weight: bold")
        self._status.setText(f"{_tr('rec_saved')}\n{session_id[:32]}...")
        if session_id:
            # Persist the optional name/project the user typed for this recording.
            name = self._name_edit.text().strip()
            project = self._proj_edit.currentText().strip()
            if name or project:
                mw = MetaWorker(session_id, name, project)
                mw.start_tracked(self._store)
            self._name_edit.clear()
            self.session_saved.emit(session_id)

    def _recording_error(self, msg: str):
        self._is_recording = False
        self._cd_timer.stop()
        self._cd_lbl.setVisible(False)
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._lang_cb.setEnabled(True)
        self._mic_cb.setEnabled(True)
        self._status.setStyleSheet("color: #e74c3c")
        self._status.setText(f"Error: {msg}")

# ── Reusable UI primitives ───────────────────────────────────────────────────
class _StatChip(QFrame):
    """Compact metric tile: a big value over a small caption."""
    def __init__(self, name: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("StatChip")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(0)
        self._value = QLabel(value)
        self._value.setObjectName("StatValue")
        self._name = QLabel(name)
        self._name.setObjectName("StatName")
        v.addWidget(self._value)
        v.addWidget(self._name)

    def set_value(self, value: str):
        self._value.setText(value)

    def set_name(self, name: str):
        self._name.setText(name)


class SectionCard(QFrame):
    """A clickable card that behaves like a checkbox: icon + name + one-line
    hint, with a visible checked state. Replaces the plain section checkboxes."""
    toggled = pyqtSignal(bool)

    def __init__(self, key: str, checked: bool = False, parent=None):
        super().__init__(parent)
        self._key = key
        self._checked = checked
        self.setObjectName("SectionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        glyph, _de, _den = _SECTION_META.get(key, ("•", "", ""))
        grid = QGridLayout(self)
        grid.setContentsMargins(11, 9, 11, 9)
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(1)
        self._icon = QLabel(glyph)
        self._icon.setFixedWidth(20)
        grid.addWidget(self._icon, 0, 0, 2, 1)
        self._name = QLabel("")
        self._name.setObjectName("SecName")
        grid.addWidget(self._name, 0, 1)
        # Parent BEFORE setVisible (same top-level-window flash as TlLine).
        self._tick = QLabel("✓", self)
        self._tick.setObjectName("SecTick")
        self._tick.setVisible(checked)
        grid.addWidget(self._tick, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self._desc = QLabel("")
        self._desc.setObjectName("SecDesc")
        self._desc.setWordWrap(True)
        grid.addWidget(self._desc, 1, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        self.retranslate()
        self._sync()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool):
        if on == self._checked:
            return
        self._checked = on
        self._sync()

    def setEnabled(self, on: bool):   # dim while generating
        super().setEnabled(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, _e):
        if self.isEnabled():
            self._checked = not self._checked
            self._sync()
            self.toggled.emit(self._checked)

    def _sync(self):
        self._tick.setVisible(self._checked)
        self.setProperty("checked", "true" if self._checked else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def retranslate(self):
        _g, de, den = _SECTION_META.get(self._key, ("•", "", ""))
        # Section display label comes from _SECTIONS (es/en); playwright is special.
        if self._key == "playwright":
            self._name.setText(_tr("pw_chk"))
        else:
            for k, les, len_, _d in _SECTIONS:
                if k == self._key:
                    self._name.setText(les if _ui_lang == "es" else len_)
                    break
        self._desc.setText(de if _ui_lang == "es" else den)


# ── Overview tab (card-based dashboard) ──────────────────────────────────────
class OverviewTab(QWidget):
    # (session_id, language, title, description, sections, provider, model,
    #  acceptance_criteria)
    generate_clicked = pyqtSignal(str, str, str, str, list, str, str, str)

    def __init__(self, store: list | None = None, parent=None):
        super().__init__(parent)
        self._store = store if store is not None else []
        self._sid = ""
        self._has_report = False
        self._restoring_ctx = False   # suppresses _save_ctx while swapping sessions
        self._models_loaded: set[str] = set()   # providers with live model list

        # Everything scrolls: the dashboard is taller than the pane.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setSpacing(12)
        lay.setContentsMargins(14, 14, 14, 14)

        # ── Metric chips row (session at a glance) ────────────
        self._chips: dict[str, _StatChip] = {}
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        for key, name in (("events", "EVENTOS"), ("shots", "CAPTURAS"),
                          ("dur", "DURACIÓN"), ("status", "ESTADO")):
            chip = _StatChip(name)
            self._chips[key] = chip
            chips_row.addWidget(chip, 1)
        lay.addLayout(chips_row)

        # ── Card 1: context ───────────────────────────────────
        ctx_card, ctx_lay = _make_card()
        self._ctx_lbl = QLabel(_tr("ov_ctx_lbl"))
        self._ctx_lbl.setObjectName("CardTitle")
        ctx_lay.addWidget(self._ctx_lbl)
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText(_tr("ov_title_ph"))
        ctx_lay.addWidget(self._title_edit)
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText(_tr("ov_desc_ph"))
        ctx_lay.addWidget(self._desc_edit)

        # Acceptance criteria of the ticket under test. Optional and per
        # session, so it stays collapsed until it is wanted (or until the
        # session already has some) instead of eating the card every time.
        ac_head = QHBoxLayout()
        ac_head.setSpacing(6)
        self._ac_toggle = QPushButton()
        self._ac_toggle.setObjectName("Ghost")
        self._ac_toggle.setCheckable(True)
        self._ac_toggle.setFixedHeight(26)
        self._ac_toggle.toggled.connect(self._on_ac_toggled)
        ac_head.addWidget(self._ac_toggle)
        ac_head.addStretch()
        self._ac_paste = QPushButton(_tr("ov_ac_paste"))
        self._ac_paste.setObjectName("Ghost")
        self._ac_paste.setToolTip(_tr("ov_ac_paste_tip"))
        self._ac_paste.setFixedHeight(26)
        self._ac_paste.clicked.connect(self._paste_ac)
        ac_head.addWidget(self._ac_paste)
        self._ac_clear = QPushButton(_tr("ov_ac_clear"))
        self._ac_clear.setObjectName("Ghost")
        self._ac_clear.setFixedHeight(26)
        self._ac_clear.clicked.connect(lambda: self._ac_edit.setPlainText(""))
        ac_head.addWidget(self._ac_clear)
        ctx_lay.addLayout(ac_head)

        self._ac_edit = QPlainTextEdit()
        self._ac_edit.setPlaceholderText(_tr("ov_ac_ph"))
        self._ac_edit.setFixedHeight(104)
        ctx_lay.addWidget(self._ac_edit)
        ac_foot = QHBoxLayout()
        self._ac_hint = QLabel(_tr("ov_ac_hint"))
        self._ac_hint.setObjectName("Muted")
        self._ac_hint.setWordWrap(True)
        ac_foot.addWidget(self._ac_hint, 1)
        self._ac_count = QLabel("")
        self._ac_count.setObjectName("Muted")
        ac_foot.addWidget(self._ac_count, 0, Qt.AlignmentFlag.AlignTop)
        ctx_lay.addLayout(ac_foot)
        self._ac_widgets = (self._ac_edit, self._ac_hint, self._ac_count)
        self._on_ac_toggled(False)      # collapsed until asked for

        # These fields belong to the session, not to the widget. Persist on
        # every keystroke so switching sessions (or restarting) never loses what
        # was typed.
        self._title_edit.textChanged.connect(self._save_ctx)
        self._desc_edit.textChanged.connect(self._save_ctx)
        self._ac_edit.textChanged.connect(self._save_ctx)
        self._ac_edit.textChanged.connect(self._update_ac_count)
        lay.addWidget(ctx_card)

        # ── Card 2: what to generate (section cards) ──────────
        sec_card, sec_lay = _make_card()
        self._sec_lbl = QLabel(_tr("ov_sec_lbl"))
        self._sec_lbl.setObjectName("CardTitle")
        sec_lay.addWidget(self._sec_lbl)

        self._sec_cards: dict[str, SectionCard] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        # AI sections + the deterministic Playwright pseudo-section, as one grid.
        all_keys = [(k, d) for k, _e, _en, d in _SECTIONS] + [("playwright", False)]
        for i, (key, default) in enumerate(all_keys):
            card = SectionCard(key, checked=default)
            if key == "playwright":
                card.setToolTip(_tr("pw_chk_tip"))
            self._sec_cards[key] = card
            grid.addWidget(card, i // 2, i % 2)
        sec_lay.addLayout(grid)
        lay.addWidget(sec_card)

        # ── Card 3: AI engine (provider / model / language) ───
        ai_card, ai_lay = _make_card()
        ai_title = QLabel("⚙  " + _tr("ov_provider_lbl").rstrip(":"))
        ai_title.setObjectName("CardTitle")
        ai_lay.addWidget(ai_title)

        eng_grid = QGridLayout()
        eng_grid.setHorizontalSpacing(10)
        eng_grid.setVerticalSpacing(7)
        self._prov_lbl = QLabel(_tr("ov_provider_lbl"))
        self._prov_lbl.setObjectName("FormLabel")
        eng_grid.addWidget(self._prov_lbl, 0, 0)
        self._prov_cb = QComboBox()
        for pid, pinfo in _PROVIDERS.items():
            self._prov_cb.addItem(pinfo["label"], userData=pid)
        eng_grid.addWidget(self._prov_cb, 0, 1)
        self._mdl_lbl = QLabel(_tr("ov_model_lbl"))
        self._mdl_lbl.setObjectName("FormLabel")
        eng_grid.addWidget(self._mdl_lbl, 1, 0)
        self._mdl_cb = QComboBox()
        eng_grid.addWidget(self._mdl_cb, 1, 1)
        self._lang_lbl = QLabel(_tr("ov_lang_lbl"))
        self._lang_lbl.setObjectName("FormLabel")
        eng_grid.addWidget(self._lang_lbl, 2, 0)
        self._lang_cb = QComboBox()
        self._lang_cb.addItem("Español", userData="es")
        self._lang_cb.addItem("English", userData="en")
        eng_grid.addWidget(self._lang_cb, 2, 1)
        eng_grid.setColumnStretch(1, 1)
        ai_lay.addLayout(eng_grid)

        # Local vs Cloud badge — makes it unmistakable whether the session data
        # stays on this machine or is sent to a remote provider.
        self._loc_badge = QLabel("")
        self._loc_badge.setObjectName("LocBadge")
        ai_lay.addWidget(self._loc_badge)

        # "Test connection" row (providers with a live model list: ollama/gemini)
        test_row = QHBoxLayout()
        self._btn_test = QPushButton(_tr("ov_test_conn"))
        self._btn_test.setFixedHeight(30)
        self._btn_test.clicked.connect(self._refresh_models)
        test_row.addWidget(self._btn_test)
        self._test_lbl = QLabel("")
        self._test_lbl.setObjectName("Muted")
        test_row.addWidget(self._test_lbl, 1)
        ai_lay.addLayout(test_row)
        lay.addWidget(ai_card)

        self._prov_cb.currentIndexChanged.connect(self._on_provider_change)
        self._on_provider_change(0)   # populate model combo for default provider

        # ── Generate CTA ──────────────────────────────────────
        self._btn = QPushButton(_tr("ov_generate"))
        self._btn.setObjectName("Accent")
        self._btn.setFixedHeight(46)
        self._btn.setEnabled(False)
        self._btn.clicked.connect(self._on_generate)
        lay.addWidget(self._btn)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setVisible(False)
        lay.addWidget(self._bar)

        self._lbl = QLabel()
        self._lbl.setObjectName("Muted")
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl)

        lay.addStretch()

    # -- acceptance criteria box ----------------------------------------
    def acceptance_criteria(self) -> str:
        return self._ac_edit.toPlainText().strip()

    def _on_ac_toggled(self, shown: bool) -> None:
        for w in self._ac_widgets:
            w.setVisible(shown)
        self._ac_paste.setVisible(shown)
        self._ac_clear.setVisible(shown)
        self._sync_ac_toggle()

    def _sync_ac_toggle(self) -> None:
        """Label the toggle, marking (with a dot) criteria kept collapsed."""
        shown = self._ac_toggle.isChecked()
        filled = bool(self._ac_edit.toPlainText().strip())
        arrow = "▾" if shown else "▸"
        mark = "  ●" if (filled and not shown) else ""
        self._ac_toggle.setText(
            f'{arrow}  {_tr("ov_ac_lbl")}  ({_tr("ov_ac_opt")}){mark}')

    def _paste_ac(self) -> None:
        """Append the clipboard to the box - the criteria usually arrive as
        one paste from the ticket, and appending never destroys what is
        already there."""
        text = (QApplication.clipboard().text() or "").strip()
        if not text:
            return
        current = self._ac_edit.toPlainText().rstrip()
        self._ac_edit.setPlainText(f"{current}\n{text}" if current else text)

    def _update_ac_count(self) -> None:
        n = len(self._ac_edit.toPlainText().strip())
        if not n:
            self._ac_count.setText("")
        elif n > AC_MAX_CHARS:
            self._ac_count.setText(
                _tr("ov_ac_over").format(n=n, m=AC_MAX_CHARS))
        else:
            self._ac_count.setText(_tr("ov_ac_chars").format(n=n))
        self._ac_count.setProperty("tone", "bad" if n > AC_MAX_CHARS else "")
        self._ac_count.style().unpolish(self._ac_count)
        self._ac_count.style().polish(self._ac_count)
        self._sync_ac_toggle()

    def _update_loc_badge(self, pid: str) -> None:
        """Colour the Local/Cloud badge for the selected provider."""
        local = pid in _LOCAL_PROVIDERS
        self._loc_badge.setText(_tr("ov_local_badge" if local else "ov_cloud_badge"))
        # Green = stays local; amber = data leaves the machine.
        fg, bg = (("#1a7f37", "rgba(26,127,55,0.12)") if local
                  else ("#b7791f", "rgba(183,121,31,0.14)"))
        self._loc_badge.setStyleSheet(
            f"#LocBadge {{ color: {fg}; background: {bg}; border-radius: 6px; "
            f"padding: 4px 8px; font-weight: 600; }}")

    def _on_provider_change(self, _idx: int = 0):
        pid = self._prov_cb.currentData() or "anthropic"
        self._update_loc_badge(pid)
        probeable = pid in _PROBEABLE
        self._btn_test.setVisible(probeable)
        self._test_lbl.setVisible(probeable)
        self._test_lbl.setText("")
        self._mdl_cb.clear()
        for mid, mlabel in _PROVIDERS[pid]["models"]:
            self._mdl_cb.addItem(mlabel, userData=mid)
        # Auto-probe the first time a probeable provider is selected so the
        # dropdown reflects the models actually available (installed locally
        # for Ollama; enabled for the API key for Gemini).
        if probeable and pid not in self._models_loaded:
            self._refresh_models()

    def _refresh_models(self):
        pid = self._prov_cb.currentData() or ""
        if pid not in _PROBEABLE:
            return
        self._btn_test.setEnabled(False)
        self._test_lbl.setText(_tr("ov_test_testing"))
        self._test_lbl.setProperty("tone", "")
        w = ProviderModelsWorker(pid)
        w.ok.connect(self._on_models)
        w.err.connect(self._on_models_err)
        w.start_tracked(self._store)

    def _on_models(self, data: dict):
        self._btn_test.setEnabled(True)
        provider = data.get("provider", "")
        # Stale reply (user already switched provider) — ignore it.
        if provider != (self._prov_cb.currentData() or ""):
            return
        ok     = bool(data.get("ok"))
        models = data.get("models", []) if isinstance(data, dict) else []
        if not ok or not models:
            tone = "bad"
            self._test_lbl.setText(
                _tr("ov_test_fail") if not ok else _tr("ov_no_models")
            )
        else:
            self._models_loaded.add(provider)
            keep = self._mdl_cb.currentData()
            self._mdl_cb.clear()
            for m in models:
                name = m.get("name", "")
                tag  = " · 👁 visión" if m.get("vision") else ""
                size = f"  ({m['size_gb']} GB)" if m.get("size_gb") else ""
                self._mdl_cb.addItem(f"{name}{size}{tag}", userData=name)
            # restore previous selection if still present
            idx = self._mdl_cb.findData(keep)
            if idx >= 0:
                self._mdl_cb.setCurrentIndex(idx)
            tone = "ok"
            self._test_lbl.setText(_tr("ov_test_ok").format(n=len(models)))
        self._test_lbl.setProperty("tone", tone)
        self._test_lbl.style().unpolish(self._test_lbl)
        self._test_lbl.style().polish(self._test_lbl)

    def _on_models_err(self, _msg: str):
        self._btn_test.setEnabled(True)
        self._test_lbl.setText(_tr("ov_test_fail"))
        self._test_lbl.setProperty("tone", "bad")
        self._test_lbl.style().unpolish(self._test_lbl)
        self._test_lbl.style().polish(self._test_lbl)

    def _on_generate(self):
        # AI sections first (report order), then the deterministic Playwright
        # pseudo-section (DetailPanel extracts it and opens the code window).
        sections = [k for k, _e, _en, _d in _SECTIONS
                    if self._sec_cards[k].isChecked()]
        if self._sec_cards["playwright"].isChecked():
            sections.append("playwright")
        if not sections:
            QMessageBox.warning(self, _tr("ov_no_sec_title"), _tr("ov_no_sec_msg"))
            return
        self.generate_clicked.emit(
            self._sid,
            self._lang_cb.currentData() or "es",
            self._title_edit.text().strip(),
            self._desc_edit.text().strip(),
            sections,
            self._prov_cb.currentData() or "anthropic",
            self._mdl_cb.currentData() or "",
            self.acceptance_criteria(),
        )

    def current_settings(self) -> dict:
        """Language / context / provider / model currently chosen by the user
        — reused by actions outside this tab (e.g. '+ test cases')."""
        return {
            "lang":        self._lang_cb.currentData() or "es",
            "title":       self._title_edit.text().strip(),
            "description": self._desc_edit.text().strip(),
            "provider":    self._prov_cb.currentData() or "anthropic",
            "model":       self._mdl_cb.currentData() or "",
            "acceptance_criteria": self.acceptance_criteria(),
        }

    # ── per-session report context (title / description) ────────────────
    def _save_ctx(self, *_):
        """Store the context fields against the session they were typed for."""
        if not self._sid or self._restoring_ctx:
            return
        st = _settings()
        st.setValue(f"session_ctx/{self._sid}/title", self._title_edit.text())
        st.setValue(f"session_ctx/{self._sid}/description", self._desc_edit.text())
        st.setValue(f"session_ctx/{self._sid}/acceptance_criteria",
                    self._ac_edit.toPlainText())

    def _restore_ctx(self, sid: str):
        st = _settings()
        title = st.value(f"session_ctx/{sid}/title", "") or ""
        desc  = st.value(f"session_ctx/{sid}/description", "") or ""
        ac    = st.value(f"session_ctx/{sid}/acceptance_criteria", "") or ""
        # Guard the setText calls: textChanged would otherwise fire _save_ctx
        # and write the outgoing session's text under the incoming session's id.
        self._restoring_ctx = True
        try:
            self._title_edit.setText(str(title))
            self._desc_edit.setText(str(desc))
            self._ac_edit.setPlainText(str(ac))
        finally:
            self._restoring_ctx = False
        # A session that already carries criteria opens with them in view.
        self._ac_toggle.setChecked(bool(str(ac).strip()))
        self._update_ac_count()

    @staticmethod
    def _duration(s: dict) -> str:
        """Human m:ss between started_at and ended_at, or '—'."""
        try:
            a = datetime.fromisoformat((s.get("started_at") or "").replace("Z", "+00:00"))
            b = datetime.fromisoformat((s.get("ended_at") or "").replace("Z", "+00:00"))
            secs = max(0, int((b - a).total_seconds()))
            return f"{secs // 60}:{secs % 60:02d}"
        except Exception:
            return "—"

    def load(self, s: dict):
        new_sid = s.get("session_id", "")
        if new_sid != self._sid:
            # Switching sessions: flush what's on screen to the outgoing session
            # before swapping in the incoming one's saved context.
            self._save_ctx()
            self._sid = new_sid
            self._restore_ctx(new_sid)
        self._sid      = new_sid
        status         = s.get("status", "captured")
        has_report     = s.get("has_report", False) or status == "done"
        generating     = status == "generating"
        self._chips["events"].set_value(str(s.get("event_count", "—")))
        self._chips["shots"].set_value(str(s.get("screenshot_count", "—")))
        self._chips["dur"].set_value(self._duration(s))
        status_map = {
            "done":       ("✓ Listo",     "✓ Ready"),
            "generating": ("⟳ Generando", "⟳ Generating"),
            "error":      ("✗ Error",     "✗ Error"),
            "captured":   ("● Capturada", "● Captured"),
        }
        es_txt, en_txt = status_map.get(status, (status, status))
        self._chips["status"].set_value(es_txt if _ui_lang == "es" else en_txt)
        self._has_report = has_report
        self._btn.setEnabled(bool(self._sid) and not generating)
        self._btn.setText(_tr("ov_regenerate") if has_report else _tr("ov_generate"))
        self._bar.setVisible(generating)
        self._lbl.setText(
            _tr("ov_generating") if generating else
            (_tr("ov_ready") if has_report else "")
        )

    def set_generating(self, v: bool):
        self._btn.setEnabled(not v)
        self._lang_cb.setEnabled(not v)
        for card in self._sec_cards.values():
            card.setEnabled(not v)
        self._title_edit.setEnabled(not v)
        self._desc_edit.setEnabled(not v)
        self._ac_edit.setEnabled(not v)
        self._ac_paste.setEnabled(not v)
        self._ac_clear.setEnabled(not v)
        self._prov_cb.setEnabled(not v)
        self._mdl_cb.setEnabled(not v)
        self._btn_test.setEnabled(not v)
        self._bar.setVisible(v)
        if v:
            prov = self._prov_cb.currentText()
            mdl  = self._mdl_cb.currentText()
            suffix = f" · {prov} / {mdl}" if prov else ""
            self._lbl.setText(_tr("ov_generating") + suffix)
        else:
            self._lbl.setText("")

    def retranslate(self):
        for key, name in (("events", "EVENTOS"), ("shots", "CAPTURAS"),
                          ("dur", "DURACIÓN"), ("status", "ESTADO")):
            en = {"EVENTOS": "EVENTS", "CAPTURAS": "SHOTS",
                  "DURACIÓN": "DURATION", "ESTADO": "STATUS"}[name]
            self._chips[key].set_name(name if _ui_lang == "es" else en)
        self._ctx_lbl.setText(_tr("ov_ctx_lbl"))
        self._title_edit.setPlaceholderText(_tr("ov_title_ph"))
        self._desc_edit.setPlaceholderText(_tr("ov_desc_ph"))
        self._ac_edit.setPlaceholderText(_tr("ov_ac_ph"))
        self._ac_hint.setText(_tr("ov_ac_hint"))
        self._ac_paste.setText(_tr("ov_ac_paste"))
        self._ac_paste.setToolTip(_tr("ov_ac_paste_tip"))
        self._ac_clear.setText(_tr("ov_ac_clear"))
        self._update_ac_count()
        self._sec_lbl.setText(_tr("ov_sec_lbl"))
        for card in self._sec_cards.values():
            card.retranslate()
        self._lang_lbl.setText(_tr("ov_lang_lbl"))
        self._prov_lbl.setText(_tr("ov_provider_lbl"))
        self._mdl_lbl.setText(_tr("ov_model_lbl"))
        self._update_loc_badge(self._prov_cb.currentData() or "anthropic")
        self._btn_test.setText(_tr("ov_test_conn"))
        if self._bar.isVisible():
            self._lbl.setText(_tr("ov_generating"))
        else:
            self._btn.setText(_tr("ov_regenerate") if self._has_report else _tr("ov_generate"))
            self._lbl.setText(_tr("ov_ready") if self._has_report else "")

# ── Events tab ───────────────────────────────────────────────────────────────
class EventsTab(QWidget):
    def __init__(self, store: list, parent=None):
        super().__init__(parent)
        self._store = store
        self._sid   = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._container = QWidget()
        self._inner     = QVBoxLayout(self._container)
        self._inner.setSpacing(0)
        self._inner.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._container)
        lay.addWidget(scroll)

    def load(self, sid: str, events: list[dict]):
        self._sid = sid
        # Build the whole list with painting suspended: adding many rows one by
        # one otherwise triggers a relayout+repaint per row, which reads as the
        # panel "flashing" while it fills. One paint at the end instead.
        self._container.setUpdatesEnabled(False)
        try:
            while self._inner.count():
                w = self._inner.takeAt(0).widget()
                if w:
                    w.deleteLater()
            if not events:
                lbl = QLabel("Sin eventos registrados." if _ui_lang == "es"
                             else "No events recorded.")
                lbl.setObjectName("Muted")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setContentsMargins(0, 20, 0, 0)
                self._inner.addWidget(lbl)
                return
            for i, ev in enumerate(events):
                self._add_row(ev, is_last=(i == len(events) - 1))
        finally:
            self._container.setUpdatesEnabled(True)

    def _add_row(self, ev: dict, is_last: bool = False):
        """One timeline entry: [time] │● gutter │ text, with an optional
        screenshot chip. The gutter draws a continuous rail with a node."""
        etype = ev.get("type", "")
        node  = {"click": "◉", "key": "⌨", "scroll": "↕",
                 "auto": "📸", "nav": "🧭"}.get(etype, "•")
        ts    = ev.get("ts", "")
        text  = ev.get("text", "")
        x, y  = ev.get("x", 0), ev.get("y", 0)
        shot  = ev.get("screenshot", "")
        try:
            ts_s = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
        except Exception:
            ts_s = ts[:8] if ts else "—"

        # Parent every widget to the container up-front. A parentless QWidget
        # is a potential top-level window: while its layout is being built (before
        # the final addWidget reparents it) it can flash on screen for a frame —
        # once per event, this reads as a window that "blinks a lot" on the tab.
        row = QWidget(self._container)
        h   = QHBoxLayout(row)
        h.setContentsMargins(6, 0, 8, 0)
        h.setSpacing(10)

        # Column 1: timestamp
        t = QLabel(ts_s)
        t.setObjectName("TlTime")
        t.setFixedWidth(58)
        t.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        t.setContentsMargins(0, 10, 0, 0)
        h.addWidget(t)

        # Column 2: rail + node (a thin vertical line behind a glyph)
        gutter = QWidget(row)
        gutter.setFixedWidth(20)
        gl = QVBoxLayout(gutter)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(0)
        gl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        dot = QLabel(node)
        dot.setObjectName("TlNode")
        dot.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        gl.addWidget(dot)
        # Parent BEFORE setVisible: setVisible(True) on a parentless widget
        # shows it as a top-level window — this was the 2x480 window flashing
        # once per event row while the timeline was being built.
        line = QFrame(gutter)
        line.setObjectName("TlLine")
        line.setVisible(not is_last)
        gl.addWidget(line, 1)
        h.addWidget(gutter)

        # Column 3: content card
        content = QVBoxLayout()
        content.setSpacing(1)
        content.setContentsMargins(0, 8, 0, 8)
        element = (ev.get("element") or "").strip()
        if element:
            main = f"<b>«{html.escape(element[:48])}»</b>"
            if text:
                main += f"  {html.escape(text[:60])}"
        else:
            main = html.escape(text) if text else f"({x}, {y})"
        main_lbl = QLabel(main)
        main_lbl.setObjectName("TlText")
        main_lbl.setTextFormat(Qt.TextFormat.RichText)
        main_lbl.setWordWrap(True)
        content.addWidget(main_lbl)
        window = (ev.get("window") or "").strip()
        url    = (ev.get("url") or "").strip()
        sub    = window or url
        if sub:
            w_lbl = QLabel(("🪟 " if window else "🔗 ") + html.escape(sub[:60]))
            w_lbl.setObjectName("TlWindow")
            content.addWidget(w_lbl)
        h.addLayout(content, 1)

        if shot:
            btn = QPushButton("🖼")
            btn.setObjectName("Ghost")
            btn.setFixedSize(34, 28)
            btn.setToolTip(shot)
            btn.clicked.connect(lambda _, s=shot: self._open_image(s))
            wrap = QVBoxLayout()
            wrap.setContentsMargins(0, 7, 0, 0)
            wrap.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
            h.addLayout(wrap)

        self._inner.addWidget(row)

    def _open_image(self, fname: str):
        if not self._sid:
            return
        w = ImageWorker(self._sid, fname)
        w.ok.connect(self._show_image)
        w.err.connect(lambda e: QMessageBox.warning(self, "Error", e))
        w.start_tracked(self._store)

    def _show_image(self, result: tuple):
        data, fname = result
        pix = QPixmap()
        pix.loadFromData(QByteArray(data))
        if not pix.isNull():
            ImageDialog(pix, fname, self).exec()

# ── Report tab ───────────────────────────────────────────────────────────────
class ReportTab(QWidget):
    more_cases_clicked     = pyqtSignal(int)   # how many new cases to generate
    add_to_context_clicked = pyqtSignal()
    save_requested         = pyqtSignal(str)   # edited Markdown, images restored

    # View modes for the report pane.
    RENDERED, MARKDOWN, EDIT = "rendered", "markdown", "edit"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw    = ""      # last SAVED Markdown (images embedded)
        self._mode   = self.RENDERED
        self._images: list[str] = []   # data-URIs pulled out of the editor text
        self._dirty  = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        toolbar = QHBoxLayout()
        self._btn_r = QPushButton(_tr("rp_rendered"))
        self._btn_m = QPushButton("Markdown")
        self._btn_e = QPushButton("✎ " + _tr("rp_edit"))
        self._btn_e.setToolTip(_tr("rp_edit_tip"))
        self._btn_e.setEnabled(False)
        self._btn_s = QPushButton(_tr("rp_save"))
        self._btn_s.setToolTip(_tr("rp_save_tip"))
        self._btn_s.setEnabled(False)
        self._btn_s.setVisible(False)
        self._btn_s.clicked.connect(self._on_save)
        self._btn_c = QPushButton(_tr("rp_copy"))
        self._btn_more = QPushButton(_tr("rp_more_cases"))
        self._btn_more.setToolTip(_tr("rp_more_tip"))
        self._btn_more.setEnabled(False)
        self._btn_more.clicked.connect(
            lambda: self.more_cases_clicked.emit(self.more_count()))
        # How many extra cases to ask for. Remembered globally: it is a working
        # habit ("give me three at a time"), not a property of one session.
        self._more_n = QSpinBox()
        self._more_n.setRange(1, 20)
        self._more_n.setToolTip(_tr("rp_more_count_tip"))
        self._more_n.setFixedHeight(28)
        self._more_n.setFixedWidth(52)
        try:
            saved_n = int(_settings().value("report/more_cases_count", 5))
        except (TypeError, ValueError):
            saved_n = 5
        self._more_n.setValue(max(1, min(20, saved_n)))
        self._more_n.valueChanged.connect(
            lambda v: _settings().setValue("report/more_cases_count", v))
        self._btn_ctx = QPushButton(_tr("ctx_add_report"))
        self._btn_ctx.setToolTip(_tr("ctx_add_tip"))
        self._btn_ctx.setEnabled(False)
        self._btn_ctx.clicked.connect(self.add_to_context_clicked.emit)
        self._btn_pdf = QPushButton("⤓ " + _tr("rp_export_pdf"))
        self._btn_pdf.setObjectName("Accent")
        for b in (self._btn_r, self._btn_m, self._btn_e, self._btn_s,
                  self._btn_c, self._btn_more, self._btn_ctx):
            b.setObjectName("Ghost")
        for b in (self._btn_r, self._btn_m, self._btn_e, self._btn_s,
                  self._btn_c, self._btn_more):
            b.setFixedHeight(28)
            toolbar.addWidget(b)
        toolbar.addWidget(self._more_n)
        for b in (self._btn_ctx, self._btn_pdf):
            b.setFixedHeight(28)
            toolbar.addWidget(b)
        toolbar.addStretch()
        self._hint_lbl = QLabel(_tr("img_click_hint"))
        self._hint_lbl.setObjectName("Muted")
        self._hint_lbl.setStyleSheet("font-size:11px;font-style:italic")
        self._hint_lbl.setVisible(False)
        toolbar.addWidget(self._hint_lbl)
        lay.addLayout(toolbar)

        # Rendered/Markdown share the browser; editing gets its own plain text
        # widget so the browser never has to be made writable.
        self._stack = QStackedWidget()
        self._view = _ReportBrowser()
        self._view.setObjectName("ReportView")
        self._view.image_clicked.connect(self._on_image_click)
        self._stack.addWidget(self._view)
        self._editor = QPlainTextEdit()
        self._editor.setObjectName("ReportEditor")
        self._editor.setFont(QFont("Consolas", 10))
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._editor.textChanged.connect(self._on_edited)
        self._stack.addWidget(self._editor)
        lay.addWidget(self._stack)

        self._btn_r.clicked.connect(lambda: self._show(self.RENDERED))
        self._btn_m.clicked.connect(lambda: self._show(self.MARKDOWN))
        self._btn_e.clicked.connect(lambda: self._show(self.EDIT))
        self._btn_c.clicked.connect(
            lambda: QApplication.clipboard().setText(self.current_markdown()))
        self._btn_pdf.clicked.connect(self._export_pdf)

    # ── screenshot placeholders ─────────────────────────────────────────────
    # A generated report embeds every screenshot as a base64 data-URI, which
    # would drown the editor in thousands of unreadable characters. Editing
    # swaps each one for a short marker and puts it back on the way out.
    _IMG_RE = re.compile(r'!\[([^\]]*)\]\((data:image/[^)]*)\)')

    def _collapse_images(self, md: str) -> str:
        self._images = []

        def _sub(m: re.Match) -> str:
            self._images.append(m.group(2))
            n = len(self._images)
            label = m.group(1) or (f"captura {n}" if _ui_lang == "es"
                                   else f"screenshot {n}")
            return f"![{label}](img://{n})"

        return self._IMG_RE.sub(_sub, md)

    def _expand_images(self, md: str) -> str:
        """Restore the data-URIs. A marker the tester deleted stays deleted;
        one that points nowhere is left untouched rather than guessed at."""
        def _sub(m: re.Match) -> str:
            idx = int(m.group(2))
            if 1 <= idx <= len(self._images):
                return f"![{m.group(1)}]({self._images[idx - 1]})"
            return m.group(0)

        return re.sub(r'!\[([^\]]*)\]\(img://(\d+)\)', _sub, md)

    # ── state ───────────────────────────────────────────────────────────────
    def current_markdown(self) -> str:
        """The report as it stands, including edits not yet saved."""
        if self._mode == self.EDIT:
            return self._expand_images(self._editor.toPlainText())
        return self._raw

    def is_dirty(self) -> bool:
        return self._dirty

    def more_count(self) -> int:
        return self._more_n.value()

    def _on_edited(self):
        if self._mode != self.EDIT:
            return          # programmatic fill, not a keystroke
        self._dirty = True
        self._btn_s.setVisible(True)
        self._btn_s.setEnabled(True)
        self._btn_s.setText(_tr("rp_save") + " ●")

    def _on_save(self):
        self._btn_s.setEnabled(False)
        self._btn_s.setText(_tr("rp_saving"))
        self.save_requested.emit(self.current_markdown())

    def save_finished(self, ok: bool):
        """Called back by the panel that owns the network worker."""
        if ok:
            self._raw = self.current_markdown()
            self._dirty = False
            self._btn_s.setText(_tr("rp_save"))
            self._btn_s.setEnabled(False)
            self._btn_s.setVisible(self._mode == self.EDIT)
        else:
            self._btn_s.setText(_tr("rp_save") + " ●")
            self._btn_s.setEnabled(True)

    def clear_dirty(self):
        self._dirty = False
        self._btn_s.setEnabled(False)
        self._btn_s.setText(_tr("rp_save"))
        self._btn_s.setVisible(self._mode == self.EDIT)

    def load(self, text: str):
        if self._dirty:
            return          # never clobber unsaved edits with a refetch
        self._raw = text
        has = bool(text.strip())
        for b in (self._btn_more, self._btn_ctx, self._btn_e):
            b.setEnabled(has)
        self._show(self._mode if has else self.RENDERED)

    def _show(self, mode: str):
        if mode == self.EDIT and not self._raw.strip():
            QMessageBox.information(self, _tr("rp_edit"), _tr("rp_edit_none"))
            return
        # Leaving the editor keeps whatever was typed: the text stays in the
        # widget and current_markdown() still returns it, so switching to the
        # rendered view to check the result never costs the edits.
        if self._mode == self.EDIT and mode != self.EDIT:
            self._raw = self.current_markdown()
        self._mode = mode
        self._btn_s.setVisible(mode == self.EDIT or self._dirty)
        if mode == self.EDIT:
            self._stack.setCurrentWidget(self._editor)
            was_dirty = self._dirty
            self._editor.setPlainText(self._collapse_images(self._raw))
            self._dirty = was_dirty      # setPlainText is not a user edit
            self._hint_lbl.setVisible(False)
            self._editor.setFocus()
            return
        self._stack.setCurrentWidget(self._view)
        if mode == self.RENDERED:
            self._view.set_html_with_images(_to_html(self._raw))
            # Show hint only when there are embedded images
            self._hint_lbl.setVisible(bool(self._view._images))
        else:
            self._view.setPlainText(self._raw)
            self._hint_lbl.setVisible(False)

    def _on_image_click(self, data: bytes, name: str):
        pix = QPixmap()
        pix.loadFromData(QByteArray(data))
        if not pix.isNull():
            ImageDialog(pix, name, self).exec()

    def placeholder(self, msg: str):
        if self._dirty:
            return          # a poll must not wipe an edit in progress
        self._raw = ""
        self._mode = self.RENDERED
        self._btn_more.setEnabled(False)
        self._btn_ctx.setEnabled(False)
        self._btn_e.setEnabled(False)
        self._btn_s.setVisible(False)
        self._stack.setCurrentWidget(self._view)
        self._view.setPlainText(msg)

    # ── PDF export (images embedded per step) ────────────────────────────────
    def _export_pdf(self):
        if not self.current_markdown().strip():
            QMessageBox.information(self, _tr("rp_export_pdf"), _tr("rp_pdf_none"))
            return
        default_name = "qa-report.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, _tr("rp_pdf_title"), default_name, "PDF (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        # Build a print-quality HTML document and register every embedded
        # data-URI image as a QTextDocument resource so it renders in the PDF.
        doc = QTextDocument()
        doc.setDefaultStyleSheet(_PDF_CSS)
        html_src = _to_html(self.current_markdown())
        idx = [0]

        def _register(m: re.Match) -> str:
            attr = m.group(0)
            comma = attr.index(",") + 1
            b64 = attr[comma:-1]
            try:
                raw = base64.b64decode(b64)
            except Exception:
                return attr
            img = QImage()
            img.loadFromData(QByteArray(raw))
            if img.isNull():
                return attr
            url = QUrl(f"pdfimg://{idx[0]}")
            doc.addResource(QTextDocument.ResourceType.ImageResource, url, img)
            idx[0] += 1
            return f'src="{url.toString()}"'

        processed = re.sub(
            r'src="data:image/[^;]+;base64,[^"]*"', _register, html_src
        )
        doc.setHtml(processed)

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        try:
            doc.print(printer)
        except Exception as e:
            QMessageBox.critical(self, _tr("rp_export_pdf"), str(e))
            return
        QMessageBox.information(
            self, _tr("rp_export_pdf"), f"{_tr('rp_pdf_saved')}:\n{path}"
        )

    def retranslate(self):
        self._btn_r.setText(_tr("rp_rendered"))
        self._btn_c.setText(_tr("rp_copy"))
        self._btn_e.setText("✎ " + _tr("rp_edit"))
        self._btn_e.setToolTip(_tr("rp_edit_tip"))
        self._btn_s.setText(_tr("rp_save") + (" ●" if self._dirty else ""))
        self._btn_s.setToolTip(_tr("rp_save_tip"))
        self._btn_more.setText(_tr("rp_more_cases"))
        self._btn_more.setToolTip(_tr("rp_more_tip"))
        self._more_n.setToolTip(_tr("rp_more_count_tip"))
        self._btn_ctx.setText(_tr("ctx_add_report"))
        self._btn_ctx.setToolTip(_tr("ctx_add_tip"))
        self._btn_pdf.setText("⤓ " + _tr("rp_export_pdf"))
        self._hint_lbl.setText(_tr("img_click_hint"))

# ── Detail panel ─────────────────────────────────────────────────────────────
class DetailPanel(QWidget):
    script_saved = pyqtSignal()   # a Playwright script was written to qa-scripts/

    def __init__(self, store: list, parent=None):
        super().__init__(parent)
        self._store = store
        self._sid   = ""
        self._session: dict = {}
        self._poll: QTimer | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(6, 4, 4, 0)
        self._title = QLabel(_tr("dp_placeholder"))
        self._title.setFont(QFont("", 13, QFont.Weight.Bold))
        header.addWidget(self._title, 1)
        self._btn_ctx = QPushButton(_tr("ctx_btn"))
        self._btn_ctx.setFixedHeight(28)
        self._btn_ctx.setEnabled(False)
        self._btn_ctx.clicked.connect(self._open_context)
        header.addWidget(self._btn_ctx)
        lay.addLayout(header)

        self._tabs = QTabWidget()
        self._ov   = OverviewTab(store)
        self._ev   = EventsTab(store)
        self._rp   = ReportTab()
        self._tabs.addTab(self._ov, _tr("tab_overview"))
        self._tabs.addTab(self._ev, _tr("tab_events"))
        self._tabs.addTab(self._rp, _tr("tab_report"))
        lay.addWidget(self._tabs)

        self._ov.generate_clicked.connect(self._do_generate)
        self._rp.more_cases_clicked.connect(self._do_more_cases)
        self._rp.add_to_context_clicked.connect(self._append_to_context)
        self._rp.save_requested.connect(self._do_save_report)
        self._tabs.currentChanged.connect(self._tab_changed)

    def load(self, session: dict):
        same = bool(self._sid) and session.get("session_id", "") == self._sid
        if not same and self._sid and self._rp.is_dirty():
            # Leaving a session with unsaved report edits: offer to keep them
            # (the worker carries the OLD id, so the write still lands right).
            if QMessageBox.question(
                    self, _tr("rp_unsaved_t"), _tr("rp_unsaved_m")
            ) == QMessageBox.StandardButton.Yes:
                self._save_report(self._sid, self._rp.current_markdown())
            self._rp.clear_dirty()
        self._sid = session.get("session_id", "")
        self._session = session
        ts        = _fmt(session.get("started_at"))
        name = (session.get("name") or "").strip()
        heading = name if name else f"{ts}  |  {self._sid[:24]}..."
        proj = (session.get("project") or "").strip()
        if proj:
            heading += f"   ·   {proj}"
        self._title.setText(heading)
        self._btn_ctx.setEnabled(bool(self._sid))
        self._ov.load(session)
        if same:
            # Same session re-handed to us (auto-refresh / rename). Header and
            # stats are now up to date; stop here. Resetting the Report tab to a
            # placeholder and re-fetching it would blink the report away for no
            # new information.
            return
        self._rp.placeholder(_tr("dp_rp_hint"))
        self._tab_changed(self._tabs.currentIndex())

    def _project(self) -> str:
        return (self._session.get("project") or "").strip()

    def _open_context(self):
        project = self._project()
        if not project:
            QMessageBox.information(self, _tr("ctx_no_project_t"),
                                    _tr("ctx_no_project_m"))
            return
        ProjectContextDialog(project, self).exec()

    def _append_to_context(self):
        """Append the current report (e.g. the exploratory analysis) to the
        project's context so future generations are informed by it."""
        project = self._project()
        if not project:
            QMessageBox.information(self, _tr("ctx_no_project_t"),
                                    _tr("ctx_no_project_m"))
            return
        report = self._rp._raw.strip()
        if not report:
            return
        from urllib.parse import quote
        try:
            existing = _get(f"/projects/{quote(project)}/context", timeout=5)
            current = existing.get("context", "") if isinstance(existing, dict) else ""
            combined = (current.rstrip() + "\n\n" + report) if current.strip() else report
            _put(f"/projects/{quote(project)}/context", {"context": combined})
        except Exception as e:
            QMessageBox.critical(self, _tr("ctx_err"), str(e))
            return
        self.statusBar_message(_tr("ctx_added") + f": {project}")

    def _tab_changed(self, idx: int):
        if idx == 1:
            self._load_events()
        elif idx == 2:
            self._load_report()

    def _load_events(self):
        if not self._sid:
            return
        w = EventsWorker(self._sid)
        w.ok.connect(lambda evs: self._ev.load(self._sid, evs))
        w.err.connect(lambda _: self._ev.load(self._sid, []))
        w.start_tracked(self._store)

    def _load_report(self):
        if not self._sid or self._rp.is_dirty():
            return          # unsaved edits outrank a refresh
        self._rp.placeholder(_tr("dp_rp_loading"))
        w = ReportWorker(self._sid)
        w.ok.connect(self._rp.load)
        w.err.connect(lambda _: self._rp.placeholder(_tr("dp_rp_none")))
        w.start_tracked(self._store)

    def _do_generate(self, sid: str, lang: str = "es",
                      title: str = "", description: str = "",
                      sections: list | None = None,
                      provider: str = "anthropic", model: str = "",
                      acceptance_criteria: str = ""):
        if not sid:
            return
        sections = list(sections or [])
        if "playwright" in sections:
            sections.remove("playwright")
            pw = PlaywrightWorker(sid, lang)
            pw.ok.connect(lambda code, s=sid: self._show_playwright(code, s))
            pw.err.connect(lambda e: QMessageBox.critical(self, _tr("pw_err"), e))
            pw.start_tracked(self._store)
        if not sections:
            return          # Playwright-only run: no AI generation needed
        self._ov.set_generating(True)
        w = GenerateWorker(sid, lang, title, description, sections,
                           provider, model, acceptance_criteria)
        w.ok.connect(self._gen_ok)
        w.err.connect(self._gen_err)
        w.start_tracked(self._store)

    def _show_playwright(self, code: str, sid: str):
        # Auto-save into qa-scripts/<project>/ so it appears under "My Scripts".
        saved_path = None
        try:
            project = (self._session.get("project") or "").strip()
            name = (self._session.get("name") or "").strip()
            saved_path = _save_script(code, project, name, sid)
            self.script_saved.emit()
        except Exception:
            saved_path = None
        dlg = CodeDialog(code, sid, self)
        if saved_path is not None:
            self.statusBar_message(f"{_tr('sc_saved_to')}: {saved_path.name}")
        dlg.show()          # separate, non-modal window

    def statusBar_message(self, msg: str):
        win = self.window()
        if isinstance(win, QMainWindow):
            win.statusBar().showMessage(msg, 6000)

    def _gen_ok(self, _result: dict):
        self._ov.set_generating(False)
        self._start_poll()

    def _gen_err(self, error: str):
        self._ov.set_generating(False)
        QMessageBox.critical(self, _tr("gen_err_title"), error)

    def _do_save_report(self, markdown: str):
        self._save_report(self._sid, markdown)

    def _save_report(self, sid: str, markdown: str):
        """PUT an edited report. The id is passed in rather than read from
        self, so a save fired while leaving a session still writes to it."""
        if not sid:
            return
        w = SaveReportWorker(sid, markdown)
        w.ok.connect(lambda _r, s=sid: self._save_report_ok(s))
        w.err.connect(self._save_report_err)
        w.start_tracked(self._store)

    def _save_report_ok(self, sid: str):
        if sid == self._sid:
            self._rp.save_finished(True)
        self.statusBar_message(_tr("rp_saved"))

    def _save_report_err(self, error: str):
        self._rp.save_finished(False)
        QMessageBox.critical(self, _tr("rp_save_err"), error)

    def _do_more_cases(self, count: int = 5):
        """'+ Test cases': append `count` new, non-duplicate cases to the
        report using the provider/model/language selected in Overview."""
        if not self._sid:
            return
        if self._rp.is_dirty():
            # The backend appends to ITS copy of the report; unsaved edits
            # would be overwritten by the result.
            if QMessageBox.question(
                    self, _tr("rp_unsaved_t"), _tr("rp_unsaved_m")
            ) == QMessageBox.StandardButton.Yes:
                self._save_report(self._sid, self._rp.current_markdown())
            self._rp.clear_dirty()
        cfg = self._ov.current_settings()
        self._rp._btn_more.setEnabled(False)
        self._rp.placeholder(_tr("rp_more_generating").format(n=count))
        w = MoreCasesWorker(
            self._sid, lang=cfg["lang"], count=count,
            title=cfg["title"], description=cfg["description"],
            provider=cfg["provider"], model=cfg["model"],
            acceptance_criteria=cfg["acceptance_criteria"],
        )
        w.ok.connect(lambda _r: self._start_poll())
        w.err.connect(self._more_cases_err)
        w.start_tracked(self._store)

    def _more_cases_err(self, error: str):
        QMessageBox.critical(self, _tr("gen_err_title"), error)
        self._load_report()   # restore the current report view

    def _start_poll(self):
        if self._poll:
            self._poll.stop()
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_status)
        self._poll.start(4_000)

    def _poll_status(self):
        if not self._sid:
            return
        w = DetailWorker(self._sid)
        w.ok.connect(self._on_poll)
        w.start_tracked(self._store)

    def retranslate(self):
        if not self._sid:
            self._title.setText(_tr("dp_placeholder"))
        self._btn_ctx.setText(_tr("ctx_btn"))
        self._tabs.setTabText(0, _tr("tab_overview"))
        self._tabs.setTabText(1, _tr("tab_events"))
        self._tabs.setTabText(2, _tr("tab_report"))
        self._ov.retranslate()
        self._rp.retranslate()

    def _on_poll(self, s: dict):
        self._ov.load(s)
        status_val = s.get("status", "")
        is_done  = status_val == "done" or s.get("has_report")
        is_error = status_val == "error" or status_val.startswith("error:")
        if is_done or is_error:
            if self._poll:
                self._poll.stop()
                self._poll = None
            if is_error:
                # Show the error detail to the user
                detail = status_val[len("error:"):].strip() if ":" in status_val else status_val
                QMessageBox.critical(self, _tr("gen_err_title"), detail or "Unknown error")
                if self._tabs.currentIndex() == 2:
                    self._load_report()   # restore whatever report exists
            elif self._tabs.currentIndex() == 2:
                self._load_report()

# ── Scripts panel (My Scripts) ───────────────────────────────────────────────
class ScriptsPanel(QWidget):
    """Browse generated Playwright scripts grouped by project, and run them
    headed (opens a real browser you can watch) via `npx playwright test`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._setup_stage = 0   # 0=idle, 1=npm install, 2=browser install

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self._title = QLabel("‹/›  " + _tr("sc_title"))
        self._title.setObjectName("PageTitle")
        lay.addWidget(self._title)

        self._hint = QLabel(_tr("sc_hint"))
        self._hint.setObjectName("Muted")
        self._hint.setWordWrap(True)
        lay.addWidget(self._hint)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.currentItemChanged.connect(self._on_change)
        self._tree.itemDoubleClicked.connect(lambda *_: self._run())
        lay.addWidget(self._tree, 1)

        row = QHBoxLayout()
        self._btn_run = QPushButton(_tr("sc_run"))
        self._btn_run.setObjectName("Accent")
        self._btn_run.setEnabled(False)
        self._btn_run.clicked.connect(self._run)
        row.addWidget(self._btn_run)

        self._btn_open = QPushButton(_tr("sc_open"))
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._open_folder)
        row.addWidget(self._btn_open)

        self._btn_del = QPushButton(_tr("sc_delete"))
        self._btn_del.setObjectName("Danger")
        self._btn_del.setEnabled(False)
        self._btn_del.clicked.connect(self._delete)
        row.addWidget(self._btn_del)

        row.addStretch()
        self._btn_creds = QPushButton(_tr("creds_btn"))
        self._btn_creds.clicked.connect(self._edit_creds)
        row.addWidget(self._btn_creds)

        self._btn_setup = QPushButton(_tr("sc_setup"))
        self._btn_setup.clicked.connect(lambda: self._start_setup(force=True))
        row.addWidget(self._btn_setup)

        self._btn_ref = QPushButton(_tr("sc_refresh"))
        self._btn_ref.clicked.connect(self.refresh)
        row.addWidget(self._btn_ref)
        lay.addLayout(row)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        lay.addWidget(self._status)

        self._log = QPlainTextEdit()
        self._log.setObjectName("Terminal")
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(180)
        mono = QFont("Consolas"); mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        self._log.setFont(mono)
        self._log.setVisible(False)
        lay.addWidget(self._log)

        self.refresh()

    # ── listing ─────────────────────────────────────────────────────────
    def refresh(self):
        cur_path = self._selected_path()
        self._tree.clear()
        groups = _scan_scripts()
        if not groups:
            placeholder = QTreeWidgetItem([_tr("sc_empty")])
            placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(placeholder)
            self._update_buttons(None)
            return
        to_select = None
        for proj, specs in groups.items():
            top = QTreeWidgetItem([f"{proj}  ({len(specs)})"])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            f = top.font(0); f.setBold(True); top.setFont(0, f)
            self._tree.addTopLevelItem(top)
            top.setExpanded(True)
            for spec in specs:
                child = QTreeWidgetItem([spec.name])
                child.setData(0, Qt.ItemDataRole.UserRole, str(spec))
                child.setToolTip(0, str(spec))
                top.addChild(child)
                if cur_path and str(spec) == cur_path:
                    to_select = child
        if to_select is not None:
            self._tree.setCurrentItem(to_select)

    def _selected_path(self) -> str | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return data if isinstance(data, str) else None

    def _on_change(self, *_):
        self._update_buttons(self._selected_path())

    def _update_buttons(self, path: str | None):
        busy = self._proc is not None
        has = path is not None and not busy
        self._btn_run.setEnabled(has)
        self._btn_open.setEnabled(has)
        self._btn_del.setEnabled(has)

    # ── run ─────────────────────────────────────────────────────────────
    def _run(self):
        path = self._selected_path()
        if not path or self._proc is not None:
            return
        _ensure_scripts_scaffold()   # keep config/auth setup current
        if not _playwright_installed():
            reply = QMessageBox.question(
                self, _tr("sc_need_setup_t"), _tr("sc_need_setup_m"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._start_setup()
            return
        # Specs that log in read QA_USERNAME / QA_PASSWORD from qa-scripts/.env.
        # Running one without credentials fails cryptically at the login step —
        # offer to fill them in right now instead.
        try:
            spec_text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            spec_text = ""
        if "QA_PASSWORD" in spec_text or "QA_USERNAME" in spec_text:
            env_vals = _read_scripts_env()
            if not (env_vals.get("QA_USERNAME") and env_vals.get("QA_PASSWORD")):
                QMessageBox.information(self, _tr("creds_missing_t"),
                                        _tr("creds_missing_m"))
                if TestCredentialsDialog(self).exec() != QDialog.DialogCode.Accepted:
                    return
        # Playwright treats the positional arg as a filename filter (regex) —
        # backslashes break the match, so always pass a forward-slash path.
        rel = os.path.relpath(path, _SCRIPTS_ROOT).replace(os.sep, "/")
        self._log.clear()
        self._log.setVisible(True)
        self._status.setText(_tr("sc_running"))
        self._start_proc(["npx", "playwright", "test", "--headed", rel],
                         on_done=self._on_run_done)

    def _on_run_done(self, code: int):
        # A clear PASS/FAIL beats a raw exit code.
        self._status.setText(_tr("sc_pass") if code == 0
                             else _tr("sc_fail").format(c=code))

    # ── setup (npm install + browser download) ──────────────────────────
    def _start_setup(self, force: bool = False):
        if self._proc is not None:
            return
        if _playwright_installed() and not force:
            self._status.setText(_tr("sc_setup_done"))
            return
        _ensure_scripts_scaffold()
        self._log.clear()
        self._log.setVisible(True)
        self._status.setText(_tr("sc_setup_running"))
        self._setup_stage = 1
        self._start_proc(["npm", "install", "-D", "@playwright/test"],
                         on_done=self._on_setup_step)

    def _on_setup_step(self, code: int):
        if code != 0:
            self._setup_stage = 0
            self._status.setText(_tr("sc_setup_fail"))
            QMessageBox.critical(self, _tr("sc_setup_fail"),
                                 _tr("sc_setup_fail") + f" (exit {code})")
            return
        if self._setup_stage == 1:
            self._setup_stage = 2
            self._start_proc(["npx", "playwright", "install", "chromium"],
                             on_done=self._on_setup_step)
        else:
            self._setup_stage = 0
            self._status.setText(_tr("sc_setup_done"))

    # ── QProcess plumbing ───────────────────────────────────────────────
    def _start_proc(self, args: list[str], on_done):
        """Run a command in qa-scripts/, streaming output to the log pane.
        On Windows npm/npx are .cmd shims, so route through cmd.exe."""
        proc = QProcess(self)
        proc.setWorkingDirectory(str(_SCRIPTS_ROOT))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(
            lambda p=proc: self._append_log(bytes(p.readAllStandardOutput()).decode(errors="replace")))
        proc.finished.connect(lambda ec, _st, cb=on_done: self._proc_finished(ec, cb))
        proc.errorOccurred.connect(self._proc_error)
        self._proc = proc
        self._update_buttons(self._selected_path())
        if os.name == "nt":
            proc.start("cmd", ["/c", *args])
        else:
            proc.start(args[0], args[1:])

    def _append_log(self, text: str):
        self._log.moveCursor(self._log.textCursor().MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.moveCursor(self._log.textCursor().MoveOperation.End)

    def _proc_finished(self, exit_code: int, cb):
        self._proc = None
        self._update_buttons(self._selected_path())
        if callable(cb):
            cb(exit_code)

    def _proc_error(self, _err):
        if self._proc is None:
            return
        self._proc = None
        self._update_buttons(self._selected_path())
        self._status.setText(_tr("sc_run_err"))
        self._append_log("\n[error] " + _tr("sc_run_err") + "\n")

    def _edit_creds(self):
        if TestCredentialsDialog(self).exec() == QDialog.DialogCode.Accepted:
            self._status.setText(_tr("creds_saved"))

    # ── open / delete ───────────────────────────────────────────────────
    def _open_folder(self):
        path = self._selected_path()
        target = Path(path).parent if path else _SCRIPTS_ROOT
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _delete(self):
        path = self._selected_path()
        if not path:
            return
        reply = QMessageBox.question(
            self, _tr("sc_delete"), f"{_tr('sc_del_confirm')}\n\n{Path(path).name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except Exception as e:
            QMessageBox.critical(self, _tr("sc_delete"), str(e))
        self.refresh()

    def retranslate(self):
        self._title.setText("‹/›  " + _tr("sc_title"))
        self._hint.setText(_tr("sc_hint"))
        self._btn_run.setText(_tr("sc_run"))
        self._btn_open.setText(_tr("sc_open"))
        self._btn_del.setText(_tr("sc_delete"))
        self._btn_creds.setText(_tr("creds_btn"))
        self._btn_setup.setText(_tr("sc_setup"))
        self._btn_ref.setText(_tr("sc_refresh"))
        self.refresh()


# ── Projects panel (dedicated view to see & manage projects) ─────────────────
class ProjectsPanel(QWidget):
    """A separate view listing every project as a card: session/script counts,
    context status, and management actions (edit context, view sessions, open
    scripts, rename, delete)."""
    open_sessions = pyqtSignal(str)   # request MainWindow to show sessions of <project>
    changed       = pyqtSignal()      # projects mutated → refresh everything

    def __init__(self, store: list, parent=None):
        super().__init__(parent)
        self._store = store
        self._sessions: list[dict] = []
        self._ctx_status: dict[str, bool] = {}
        self._server_names: list[str] = []   # backend projects (incl. empty ones)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        head = QHBoxLayout()
        self._title = QLabel("▦  " + _tr("pj_title"))
        self._title.setObjectName("PageTitle")
        head.addWidget(self._title)
        head.addStretch()
        self._btn_new = QPushButton(_tr("pj_new"))
        self._btn_new.setObjectName("Accent")
        self._btn_new.clicked.connect(self._new_project)
        head.addWidget(self._btn_new)
        outer.addLayout(head)

        self._hint = QLabel(_tr("pj_hint"))
        self._hint.setObjectName("Muted")
        self._hint.setWordWrap(True)
        outer.addWidget(self._hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body = QWidget()
        self._grid = QVBoxLayout(self._body)
        self._grid.setSpacing(10)
        self._grid.setContentsMargins(0, 0, 4, 0)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._body)
        outer.addWidget(scroll, 1)

    # ── data ────────────────────────────────────────────────────────────
    def set_sessions(self, sessions: list[dict]):
        self._sessions = sessions
        self._rebuild()
        # Merge backend project names + probe context presence in the background.
        session_names = sorted(
            {(s.get("project") or "").strip() for s in sessions} - {""},
            key=str.lower)
        w = ProjectsProbeWorker(session_names)
        w.ok.connect(self._on_ctx_probe)
        w.start_tracked(self._store)

    def _project_names(self) -> list[str]:
        names = {(s.get("project") or "").strip() for s in self._sessions}
        names.discard("")
        names.update(self._server_names)   # include empty backend-only projects
        return sorted(names, key=str.lower)

    def _members(self, project: str) -> list[tuple[str, str]]:
        return [(s.get("session_id", ""), (s.get("name") or "").strip())
                for s in self._sessions
                if (s.get("project") or "").strip() == project]

    def _on_ctx_probe(self, result: dict):
        self._server_names = result.get("names", [])
        self._ctx_status = result.get("status", {})
        self._rebuild()

    def _rebuild(self):
        while self._grid.count():
            it = self._grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        names = self._project_names()
        if not names:
            empty = QLabel(_tr("pj_empty"))
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 30, 0, 0)
            self._grid.addWidget(empty)
            return

        scripts = _scan_scripts()
        for name in names:
            self._grid.addWidget(self._project_card(name, scripts))

    def _project_card(self, name: str, scripts: dict) -> QWidget:
        card, lay = _make_card()
        n_sessions = sum(1 for s in self._sessions
                         if (s.get("project") or "").strip() == name)
        n_scripts = len(scripts.get(_slug(name), []))

        top = QHBoxLayout()
        title = QLabel(name)
        title.setObjectName("CardTitle")
        top.addWidget(title)
        top.addStretch()
        has_ctx = self._ctx_status.get(name, False)
        ctx_lbl = QLabel(_tr("pj_has_ctx") if has_ctx else _tr("pj_no_ctx"))
        ctx_lbl.setObjectName("Muted")
        ctx_lbl.setProperty("tone", "ok" if has_ctx else "")
        top.addWidget(ctx_lbl)
        lay.addLayout(top)

        counts = QLabel(
            _tr("pj_sessions_n").format(n=n_sessions) + "    ·    "
            + _tr("pj_scripts_n").format(n=n_scripts))
        counts.setObjectName("SessMeta")
        lay.addWidget(counts)

        sep = QFrame(); sep.setObjectName("Sep"); sep.setFixedHeight(1)
        lay.addWidget(sep)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        b_ctx = QPushButton("📝 " + _tr("pj_edit_ctx"))
        b_ctx.setObjectName("Ghost")
        b_ctx.clicked.connect(lambda _=False, p=name: self._edit_context(p))
        actions.addWidget(b_ctx)
        b_sess = QPushButton("▤ " + _tr("pj_view_sessions"))
        b_sess.setObjectName("Ghost")
        b_sess.clicked.connect(lambda _=False, p=name: self.open_sessions.emit(p))
        actions.addWidget(b_sess)
        b_scr = QPushButton("‹/› " + _tr("pj_open_scripts"))
        b_scr.setObjectName("Ghost")
        b_scr.setEnabled(n_scripts > 0)
        b_scr.clicked.connect(lambda _=False, p=name: self._open_scripts(p))
        actions.addWidget(b_scr)
        actions.addStretch()
        b_ren = QPushButton(_tr("pj_rename"))
        b_ren.setObjectName("Ghost")
        b_ren.clicked.connect(lambda _=False, p=name: self._rename(p))
        actions.addWidget(b_ren)
        b_del = QPushButton(_tr("pj_delete"))
        b_del.setObjectName("Danger")
        b_del.clicked.connect(lambda _=False, p=name: self._delete(p))
        actions.addWidget(b_del)
        lay.addLayout(actions)
        return card

    # ── actions ─────────────────────────────────────────────────────────
    def _edit_context(self, project: str):
        ProjectContextDialog(project, self).exec()
        self.set_sessions(self._sessions)   # refresh context status

    def _open_scripts(self, project: str):
        target = _SCRIPTS_ROOT / _slug(project)
        if not target.exists():
            target = _SCRIPTS_ROOT
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _new_project(self):
        name, ok = QInputDialog.getText(
            self, _tr("pj_new_title"), _tr("pj_new_prompt"))
        name = (name or "").strip()
        if not ok or not name:
            return
        # Materialise the project by creating an (empty) context entry so it
        # shows up even before any session is assigned. Then open the editor.
        from urllib.parse import quote
        try:
            _put(f"/projects/{quote(name)}/context", {"context": ""})
        except Exception:
            pass
        ProjectContextDialog(name, self).exec()
        self.changed.emit()

    def _rename(self, project: str):
        new, ok = QInputDialog.getText(
            self, _tr("pj_rename_title"),
            _tr("pj_rename_prompt").format(p=project), text=project)
        new = (new or "").strip()
        if not ok or not new or new == project:
            return
        self._mutate("rename", project, new, _tr("pj_rename_busy"))

    def _delete(self, project: str):
        n = sum(1 for s in self._sessions
                if (s.get("project") or "").strip() == project)
        reply = QMessageBox.question(
            self, _tr("pj_del_title"),
            _tr("pj_del_msg").format(p=project, n=n),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._mutate("delete", project, "", _tr("pj_del_busy"))

    def _mutate(self, action: str, old: str, new: str, busy_msg: str):
        self._btn_new.setEnabled(False)
        win = self.window()
        if isinstance(win, QMainWindow):
            win.statusBar().showMessage(busy_msg)
        w = ProjectMutateWorker(action, old, new, self._members(old))
        w.ok.connect(lambda _t: self._on_mutated())
        w.err.connect(self._on_mutate_err)
        w.start_tracked(self._store)

    def _on_mutated(self):
        self._btn_new.setEnabled(True)
        self.changed.emit()

    def _on_mutate_err(self, msg: str):
        self._btn_new.setEnabled(True)
        QMessageBox.critical(self, _tr("pj_title"), msg)
        self.changed.emit()

    def retranslate(self):
        self._title.setText("▦  " + _tr("pj_title"))
        self._btn_new.setText(_tr("pj_new"))
        self._hint.setText(_tr("pj_hint"))
        self._rebuild()


# ── Main window ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._workers: list[_W] = []
        self.setWindowTitle("FullQA.ai")
        self.setMinimumSize(1100, 700)
        self._build()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(REFRESH_MS)

        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start(HEALTH_MS)

        self._check_health()
        self._refresh()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay  = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Header bar ─────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("Header")
        hdr = QHBoxLayout(header)
        hdr.setContentsMargins(18, 12, 18, 12)
        hdr.setSpacing(10)

        mark = QLabel("◆")
        mark.setObjectName("LogoMark")
        hdr.addWidget(mark)
        logo = QLabel("FullQA.ai")
        logo.setObjectName("LogoText")
        hdr.addWidget(logo)
        tagline = QLabel("AI QA Documentation")
        tagline.setObjectName("Tagline")
        hdr.addWidget(tagline)
        hdr.addStretch()

        self._ui_lang_lbl = QLabel(_tr("ui_lang_lbl"))
        self._ui_lang_lbl.setObjectName("Muted")
        hdr.addWidget(self._ui_lang_lbl)
        self._ui_lang_cb = QComboBox()
        self._ui_lang_cb.addItem("Español", userData="es")
        self._ui_lang_cb.addItem("English", userData="en")
        self._ui_lang_cb.setFixedWidth(96)
        self._ui_lang_cb.setView(QListView())
        self._ui_lang_cb.setMaxVisibleItems(8)
        self._ui_lang_cb.currentIndexChanged.connect(self._on_ui_lang_change)
        hdr.addWidget(self._ui_lang_cb)

        self._theme_lbl = QLabel(_tr("theme_lbl"))
        self._theme_lbl.setObjectName("Muted")
        hdr.addWidget(self._theme_lbl)
        self._theme_cb = QComboBox()
        self._theme_cb.addItem(_tr("theme_light"), userData="light")
        self._theme_cb.addItem(_tr("theme_dark"), userData="dark")
        self._theme_cb.setFixedWidth(96)
        self._theme_cb.setView(QListView())
        self._theme_cb.setMaxVisibleItems(8)
        _ti = self._theme_cb.findData(_theme)
        if _ti >= 0:
            self._theme_cb.setCurrentIndex(_ti)
        self._theme_cb.currentIndexChanged.connect(self._on_theme_change)
        hdr.addWidget(self._theme_cb)

        self._health_lbl = QLabel(_tr("connecting"))
        self._health_lbl.setObjectName("Pill")
        self._health_lbl.setProperty("state", "warn")
        hdr.addWidget(self._health_lbl)

        self._btn_ref = QPushButton(_tr("refresh"))
        self._btn_ref.setFixedHeight(32)
        self._btn_ref.clicked.connect(self._refresh)
        hdr.addWidget(self._btn_ref)
        lay.addWidget(header)

        # ── Offline banner (hidden unless backend is down) ─────────
        self._banner = QLabel(_tr("offline_banner"))
        self._banner.setObjectName("Banner")
        self._banner.setVisible(False)
        lay.addWidget(self._banner)

        # ── Body ───────────────────────────────────────────────────
        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(8, 8, 8, 6)
        body_lay.setSpacing(8)
        lay.addWidget(body, 1)

        # Left: navigation sidebar (My Sessions / My Scripts / Record)
        self._nav = QListWidget()
        self._nav.setObjectName("Nav")
        self._nav.setFixedWidth(170)
        for key, glyph in _NAV_ITEMS:
            QListWidgetItem(f"{glyph}   {_tr(key)}", self._nav)
        self._nav.currentRowChanged.connect(self._on_nav)
        body_lay.addWidget(self._nav)

        # Right: stacked pages
        self._stack = QStackedWidget()
        body_lay.addWidget(self._stack, 1)

        # Page 0 — My Sessions: browser (grouped, thumbnails) + detail
        sessions_page = QSplitter(Qt.Orientation.Horizontal)
        sessions_page.setMinimumWidth(0)
        self._browser = SessionBrowser()
        self._browser.setMinimumWidth(260)
        self._browser.setMaximumWidth(380)
        self._browser.selected.connect(self._on_selected)
        self._browser.delete_clicked.connect(self._delete_session)
        self._browser.rename_requested.connect(self._rename_session)
        sessions_page.addWidget(self._browser)
        self._detail = DetailPanel(self._workers)
        self._detail.script_saved.connect(self._on_script_saved)
        sessions_page.addWidget(self._detail)
        sessions_page.setStretchFactor(0, 0)
        sessions_page.setStretchFactor(1, 1)
        self._stack.addWidget(sessions_page)

        # Page 1 — Projects
        self._projects = ProjectsPanel(self._workers)
        self._projects.open_sessions.connect(self._show_project_sessions)
        self._projects.changed.connect(self._refresh)
        self._stack.addWidget(self._projects)

        # Page 2 — My Scripts
        self._scripts = ScriptsPanel()
        self._stack.addWidget(self._scripts)

        # Page 3 — Record
        self._recorder = RecorderPanel(self._workers)
        self._recorder.session_saved.connect(self._on_session_saved)
        rec_scroll = QScrollArea()
        rec_scroll.setWidgetResizable(True)
        rec_scroll.setWidget(self._recorder)
        self._stack.addWidget(rec_scroll)

        self._nav.setCurrentRow(0)

    def _check_health(self):
        w = HealthWorker()
        w.ok.connect(self._on_health)
        w.start_tracked(self._workers)

    def _on_health(self, ok: bool):
        self._health_lbl.setText(_tr("api_online") if ok else _tr("api_offline"))
        self._health_lbl.setProperty("state", "ok" if ok else "bad")
        # Re-polish so the property-based stylesheet takes effect
        self._health_lbl.style().unpolish(self._health_lbl)
        self._health_lbl.style().polish(self._health_lbl)

    def _refresh(self):
        self.statusBar().showMessage(_tr("sb_refreshing"))
        w = SessionsWorker()
        w.ok.connect(self._on_sessions)
        w.err.connect(lambda e: self.statusBar().showMessage(f"Error: {e}"))
        w.start_tracked(self._workers)

    def _on_sessions(self, data):
        if isinstance(data, dict):
            sessions = data.get("sessions", [])
            offline  = data.get("offline", False)
        else:
            sessions = data if isinstance(data, list) else []
            offline  = False
        self._banner.setVisible(offline)
        self._browser.update_sessions(sessions)
        self._projects.set_sessions(sessions)
        self._recorder.set_projects(self._browser.projects())
        self.statusBar().showMessage(
            f"{len(sessions)} sesion(es)  -  {datetime.now().strftime('%H:%M:%S')}"
        )

    def _on_nav(self, row: int):
        if row < 0:
            return
        self._stack.setCurrentIndex(row)
        key = _NAV_ITEMS[row][0] if row < len(_NAV_ITEMS) else ""
        if key == "nav_scripts":        # rescan scripts on entry
            self._scripts.refresh()

    def _show_project_sessions(self, project: str):
        """Jump from the Projects view to My Sessions, filtered to <project>."""
        self._nav.setCurrentRow(0)
        self._browser.filter_to(project)

    def _on_script_saved(self):
        self._scripts.refresh()

    def _on_selected(self, session: dict):
        self._detail.load(session)

    def _rename_session(self, session: dict):
        sid = session.get("session_id", "")
        if not sid:
            return
        dlg = RenameDialog(
            session.get("name") or "",
            session.get("project") or "",
            self._browser.projects(),
            self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, project = dlg.values()
        w = MetaWorker(sid, name, project)
        w.ok.connect(lambda _sid: self._refresh())
        w.err.connect(lambda e: QMessageBox.critical(self, _tr("rename_err"), e))
        w.start_tracked(self._workers)

    def _delete_session(self, session: dict):
        sid = session.get("session_id", "")
        if not sid:
            return
        reply = QMessageBox.question(
            self,
            _tr("del_title"),
            f"{_tr('del_msg')}\n\n{sid}\n\n{_tr('del_warning')}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        w = DeleteWorker(sid)
        w.ok.connect(self._on_deleted)
        w.err.connect(lambda e: QMessageBox.critical(self, _tr("del_err_title"), e))
        w.start_tracked(self._workers)

    def _on_deleted(self, sid: str):
        _settings().remove(f"session_ctx/{sid}")   # drop its saved report context
        self.statusBar().showMessage(f"Sesion eliminada: {sid[:32]}...")
        self._refresh()

    def _on_session_saved(self, _session_id: str):
        """Refresh session list after a new recording is saved."""
        self._refresh()

    def _on_ui_lang_change(self, _idx: int):
        global _ui_lang
        _ui_lang = self._ui_lang_cb.currentData() or "es"
        self._retranslate()

    def _on_theme_change(self, _idx: int):
        theme = self._theme_cb.currentData() or "light"
        _apply_theme(theme)
        _settings().setValue("theme", theme)

    def _retranslate(self):
        self._ui_lang_lbl.setText(_tr("ui_lang_lbl"))
        self._theme_lbl.setText(_tr("theme_lbl"))
        self._theme_cb.setItemText(0, _tr("theme_light"))
        self._theme_cb.setItemText(1, _tr("theme_dark"))
        self._btn_ref.setText(_tr("refresh"))
        for row, (key, glyph) in enumerate(_NAV_ITEMS):
            item = self._nav.item(row)
            if item:
                item.setText(f"{glyph}   {_tr(key)}")
        self._browser.retranslate()
        self._projects.retranslate()
        self._scripts.retranslate()
        self._recorder.retranslate()
        self._detail.retranslate()

# ── Entry point ──────────────────────────────────────────────────────────────
def main():
    # Ensure CWD = project root so session.py writes qa-sessions/ in the right place
    os.chdir(_PROJECT_ROOT)
    app = QApplication(sys.argv)
    app.setApplicationName("FullQA.ai")
    app.setOrganizationName("FullQA.ai")
    app.setStyle("Fusion")
    # Light by default; never follow the OS theme. Remember the user's choice.
    saved = _settings().value("theme", "light")
    _apply_theme(saved if saved in _PALETTES else "light")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()