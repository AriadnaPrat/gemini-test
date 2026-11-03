import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-")


def read_prompts(csv_path):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    required = {"prompt_id", "text", "expected_type"}
    if not rows:
        raise ValueError(f"No hay filas en {csv_path}")
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"Faltan columnas en prompts.csv: {sorted(missing)}")
    return rows


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def start_dumpcap(exe, interface, pcap_path, log_path):
    if not Path(exe).exists():
        raise FileNotFoundError(f"No encuentro el ejecutable dumpcap configurado: {exe}")
    # CTRL_BREAK_EVENT permite solicitar un cierre limpio en Windows.
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    log_file = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            [exe, "-i", str(interface), "-w", str(pcap_path)],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    except PermissionError as exc:
        log_file.close()
        raise PermissionError(
            f"No tengo permiso para ejecutar {exe}. En WSL, añade tu usuario al "
            "grupo wireshark y reinicia WSL; consulta la sección 4 del README."
        ) from exc
    except OSError:
        log_file.close()
        raise
    time.sleep(1.5)
    if proc.poll() is not None:
        log_file.close()
        raise RuntimeError(f"dumpcap terminó al arrancar. Consulta {log_path}")
    return proc, log_file


def stop_dumpcap(proc, log_file):
    if proc.poll() is None:
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGINT)
            proc.wait(timeout=15)
        except Exception:
            # Último recurso; puede perderse el cierre limpio del fichero.
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    log_file.close()


def get_response_text(page, selector):
    locator = page.locator(selector)
    count = locator.count()
    if count == 0:
        return ""
    return locator.nth(count - 1).inner_text(timeout=5000).strip()


def is_signed_out(page):
    sign_in_buttons = page.get_by_role("button", name="Sign in", exact=True)
    return any(
        sign_in_buttons.nth(index).is_visible()
        for index in range(sign_in_buttons.count())
    )


def start_new_chat(page, selectors, timeout_ms):
    new_chat = page.locator(selectors["new_chat"])
    for index in range(new_chat.count()):
        button = new_chat.nth(index)
        if button.is_visible():
            button.click(timeout=timeout_ms)
            return

    chat_controls = page.locator("button, [role='button'], a")
    visible_controls = []
    new_words = (
        "new", "nou", "nuevo", "nueva", "nova", "novo", "nouvelle", "neuer",
        "nuova", "start", "create", "inicia", "iniciar", "crear", "comenca",
    )
    chat_words = ("chat", "conversation", "convers", "xat", "discussion")
    for index in range(chat_controls.count()):
        control = chat_controls.nth(index)
        if not control.is_visible():
            continue

        labels = (
            control.get_attribute("aria-label") or "",
            control.get_attribute("title") or "",
            control.inner_text(),
        )
        label = " ".join(labels).strip()
        if label:
            visible_controls.append(label)
        normalized_label = unicodedata.normalize("NFKD", label).encode(
            "ascii", "ignore"
        ).decode("ascii").casefold()
        if (
            any(word in normalized_label for word in new_words)
            and any(word in normalized_label for word in chat_words)
        ):
            control.click(timeout=timeout_ms)
            return

    prompt_box = page.locator(selectors["prompt_input"])
    has_prompt_box = any(
        prompt_box.nth(index).is_visible()
        for index in range(prompt_box.count())
    )
    if has_prompt_box and page.locator(selectors["response_container"]).count() == 0:
        return

    raise RuntimeError(
        "No se encontró el control para iniciar un chat nuevo y la página no parece "
        "ser un chat vacío. Ejecuta inspect_gemini.py con la sesión iniciada. "
        f"Controles visibles: {visible_controls[:30]}"
    )


def send_prompt(page, selectors, timeout_ms):
    send_button = page.locator(selectors["send_button"])
    for index in range(send_button.count()):
        button = send_button.nth(index)
        if button.is_visible() and button.is_enabled():
            button.click(timeout=timeout_ms)
            return

    localized_send_button = page.get_by_role(
        "button",
        name=re.compile(r"\b(send|enviar|envia|submit)\b", re.IGNORECASE),
    )
    for index in range(localized_send_button.count()):
        button = localized_send_button.nth(index)
        if button.is_visible() and button.is_enabled():
            button.click(timeout=timeout_ms)
            return

    raise RuntimeError(
        "No se encontró un botón de envío visible y habilitado. No se envió el "
        "prompt con Enter; revisa el selector selectors.send_button."
    )


def wait_for_response(page, cfg):
    selectors = cfg["selectors"]
    timing = cfg["timing"]
    response_selector = selectors["response_container"]
    stop_selector = selectors.get("generating_indicator")
    deadline = time.monotonic() + timing["response_timeout_seconds"]
    last_text = ""
    stable_since = None
    started_at = time.monotonic()

    while time.monotonic() < deadline:
        text = get_response_text(page, response_selector)
        stop_visible = False
        if stop_selector:
            try:
                stop_visible = page.locator(stop_selector).first.is_visible(timeout=500)
            except Exception:
                stop_visible = False

        if text and text != last_text:
            last_text = text
            stable_since = time.monotonic()
        elif text and stable_since is None:
            stable_since = time.monotonic()

        enough_time = (time.monotonic() - started_at) >= 5
        stable = stable_since is not None and (
            time.monotonic() - stable_since >= timing["stable_text_seconds"]
        )
        if text and enough_time and stable and not stop_visible:
            return text
        time.sleep(timing["poll_interval_seconds"])

    raise TimeoutError("No se pudo confirmar el fin de la respuesta dentro del tiempo configurado.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--limit", type=int, default=None, help="Limita el número de prompts; útil para pruebas.")
    parser.add_argument("--start-row", type=int, default=1, help="Fila de datos CSV, empezando en 1 (sin contar cabecera).")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    project_dir = config_path.parent
    csv_path = (project_dir / cfg["csv_path"]).resolve()
    output_dir = (project_dir / cfg["output_dir"]).resolve()
    user_data_dir = (project_dir / cfg["browser_user_data_dir"]).resolve()
    rows = read_prompts(csv_path)
    rows = rows[args.start_row - 1:]
    limit = args.limit if args.limit is not None else cfg.get("limit")
    if limit:
        rows = rows[:limit]

    print(f"Prompts en esta ejecución: {len(rows)}")
    print("Se abrirá Chrome visible. No cierres la ventana durante la ejecución.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=bool(cfg.get("headless", False)),
            channel=cfg.get("browser_channel", "chrome"),
            viewport={"width": 1440, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(cfg["timing"]["element_timeout_ms"])
        page.goto(cfg["gemini_url"], wait_until="domcontentloaded",
                  timeout=cfg["timing"]["navigation_timeout_ms"])

        if cfg.get("pause_for_manual_login", True):
            while True:
                input("\nInicia sesión en Gemini y pulsa ENTER cuando la interfaz esté lista... ")
                if not is_signed_out(page):
                    break
                print("[AVISO] Gemini todavía muestra 'Sign in'. Inicia sesión en Chrome antes de continuar.")

        selectors = cfg["selectors"]
        for index, row in enumerate(rows, start=args.start_row):
            prompt_id = str(row["prompt_id"]).strip()
            prompt_text = str(row["text"])
            expected_type = str(row["expected_type"]).strip()
            timestamp_slug = datetime.now().strftime("%Y%m%d-%H%M%S")
            session_id = f"{timestamp_slug}_{safe_name(cfg['run_label'])}_{safe_name(prompt_id)}_r{cfg.get('repetition', 1)}"
            session_dir = output_dir / session_id
            session_dir.mkdir(parents=True, exist_ok=False)
            pcap_path = session_dir / "capture.pcapng"
            capture_log = session_dir / "dumpcap.log"

            meta = {
                "session_id": session_id,
                "prompt_id": prompt_id,
                "service": "gemini",
                "client": "browser",
                "automation": "Playwright Python",
                "model": cfg.get("model_name", ""),
                "repetition": cfg.get("repetition", 1),
                "group": row.get("group", ""),
                "wording": row.get("wording", ""),
                "source": row.get("source", ""),
                "expected_type": expected_type,
                "prompt_utf8_bytes": len(prompt_text.encode("utf-8")),
                "started_at": None,
                "prompt_sent_at": None,
                "response_finished_at": None,
                "capture_interface": cfg.get("interface"),
                "capture_file": "capture.pcapng",
                "status": "started",
                "notes": []
            }
            groundtruth = {
                "session_id": session_id,
                "prompt_id": prompt_id,
                "prompt_text": prompt_text,
                "answer_text": "",
                "answer_word_count": None,
                "response_type": expected_type,
                "status": "pending",
                "notes": []
            }

            capture_proc = None
            capture_log_file = None
            try:
                # Cada prompt debe comenzar en un chat nuevo.
                page.goto(cfg["gemini_url"], wait_until="domcontentloaded",
                          timeout=cfg["timing"]["navigation_timeout_ms"])
                if is_signed_out(page):
                    raise RuntimeError(
                        "Gemini muestra el botón 'Sign in'. Inicia sesión en Chrome "
                        "antes de ejecutar el experimento."
                    )
                start_new_chat(
                    page, selectors, cfg["timing"]["element_timeout_ms"]
                )

                prompt_box = page.locator(selectors["prompt_input"])
                prompt_box.wait_for(state="visible", timeout=cfg["timing"]["element_timeout_ms"])
                prompt_box.fill(prompt_text)

                meta["started_at"] = now_iso()
                capture_proc, capture_log_file = start_dumpcap(
                    cfg["dumpcap_path"], cfg["interface"], pcap_path, capture_log
                )
                meta["capture_started_at"] = now_iso()

                meta["prompt_sent_at"] = now_iso()
                send_prompt(
                    page,
                    selectors,
                    cfg["timing"]["element_timeout_ms"],
                )

                answer = wait_for_response(page, cfg)
                meta["response_finished_at"] = now_iso()
                groundtruth["answer_text"] = answer
                words = len(answer.split())
                groundtruth["answer_word_count"] = words
                if words <= 100:
                    derived_type = "short"
                elif words >= 300:
                    derived_type = "long"
                else:
                    derived_type = "ambiguous"
                    groundtruth["notes"].append(f"ambiguous length: {words} words")
                groundtruth["derived_response_type"] = derived_type
                groundtruth["response_type"] = expected_type if derived_type == "ambiguous" else derived_type
                groundtruth["status"] = "complete"
                meta["status"] = "complete"

            except Exception as exc:
                meta["status"] = "failed"
                meta["error"] = f"{type(exc).__name__}: {exc}"
                groundtruth["status"] = "failed"
                groundtruth["notes"].append(meta["error"])
                print(f"[ERROR] {prompt_id}: {exc}")
            finally:
                if capture_proc is not None:
                    stop_dumpcap(capture_proc, capture_log_file)
                    meta["capture_stopped_at"] = now_iso()
                meta["pcap_exists"] = pcap_path.exists()
                meta["pcap_size_bytes"] = pcap_path.stat().st_size if pcap_path.exists() else 0
                if meta["pcap_size_bytes"] == 0:
                    meta["notes"].append("PCAPNG ausente o vacío; revisar dumpcap.log e interfaz.")
                    if meta["status"] == "complete":
                        meta["status"] = "capture_invalid"
                write_json(session_dir / "meta.json", meta)
                write_json(session_dir / "groundtruth.json", groundtruth)
                print(f"[{meta['status']}] {prompt_id} -> {session_dir}")

            # Evita ejecutar una segunda sesión si la captura no se cerró correctamente.
            if meta["status"] == "failed":
                print("La sesión falló. Se continúa con el siguiente prompt; revisa los archivos de esta sesión.")

        context.close()


if __name__ == "__main__":
    main()
