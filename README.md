# Gemini Browser + Playwright + dumpcap

Plantilla inicial para automatizar prompts de `prompts.csv` en Gemini Browser con Chrome visible y capturar una sesión por prompt.

## Antes de empezar

- Windows 10/11 recomendado.
- Python 3.10+.
- Google Chrome instalado.
- Wireshark instalado (incluye `dumpcap.exe` y Npcap).
- Permiso para capturar tráfico en el equipo/red.
- `prompts.csv` con estas columnas: `prompt_id,text,expected_type,group,wording,source`.

**Importante:** el proyecto no usa la API de Gemini. Automatiza la interfaz web. Respeta los términos de servicio y límites del sitio. La interfaz de Gemini puede cambiar; los selectores de `config.json` deben validarse en tu navegador antes de un experimento completo.

## 1. Instalar

Abre PowerShell en esta carpeta:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

Playwright utilizará Chrome instalado (`browser_channel: "chrome"`). Si no encuentra Chrome, instala Chrome o cambia la configuración de canal.

## 2. Preparar archivos

Copia tu `prompts.csv` a esta carpeta. Copia `config.example.json` como `config.json`.

Edita `config.json`:
- `dumpcap_path`: ruta real a `dumpcap.exe`.
- `interface`: número o nombre que aparece en `dumpcap -D`.
- `model_name`: modelo que aparece en Gemini.
- `limit`: deja `1` para la primera prueba; cambia a `60` después de validar.
- `repetition`: número de repetición.
- `selectors`: selectores correctos para el idioma y versión de Gemini.

Lista interfaces:

```powershell
& "C:\Program Files\Wireshark\dumpcap.exe" -D
```

No asumas que la interfaz Wi-Fi es siempre la número 4. El número puede cambiar.

## 3. Validar los selectores de Gemini

Primero ejecuta:

```powershell
python inspect_gemini.py
```

Inicia sesión si hace falta. El inspector imprime botones visibles, campos editables y etiquetas de respuesta. Úsalo para ajustar `selectors` en `config.json`:
- `new_chat`: botón para iniciar conversación nueva.
- `prompt_input`: campo de escritura.
- `send_button`: botón enviar.
- `response_container`: contenedor de respuesta del modelo.
- `generating_indicator`: botón/indicador que existe mientras Gemini genera. Si no puedes identificarlo, deja `null`; el script usará estabilidad del texto, que es menos robusta.

No ejecutes las 60 filas hasta que una prueba aislada funcione y hayas comprobado visualmente que cada prompt se envía una sola vez a un chat nuevo.

## 4. Primera prueba de una sesión

```powershell
python run_experiment.py --config config.json --limit 1
```

Chrome se abre visible. La primera vez inicia sesión manualmente y vuelve a PowerShell para pulsar ENTER. Se guarda el perfil en `browser_profile` para conservar la sesión entre ejecuciones.

Revisa:
- que Gemini haya recibido el prompt exacto;
- que la respuesta esté completa en `groundtruth.json`;
- que `capture.pcapng` se abra en Wireshark;
- que `meta.json` tenga horas y estado correctos;
- que `dumpcap.log` no contenga errores.

## 5. Ejecutar los 60 prompts

Después de validar la prueba, configura `limit` a `null` o `0` y ejecuta:

```powershell
python run_experiment.py --config config.json
```

Para continuar desde la fila de datos 21:

```powershell
python run_experiment.py --config config.json --start-row 21
```

El número de fila empieza en 1 y no cuenta la cabecera.

## Salida

Cada sesión crea una carpeta:

```text
captures/
  20261103-..._gemini_browser_T01a_r1/
    capture.pcapng
    dumpcap.log
    meta.json
    groundtruth.json
```

La etiqueta final se deriva de `len(answer_text.split())`:
- <=100: `short`
- >=300: `long`
- 101-299: `ambiguous`, se conserva y se anota; `response_type` conserva `expected_type`.

## Limitaciones metodológicas importantes

1. `capture.pcapng` contiene todo el tráfico de la interfaz durante esa ventana, no solo tráfico de Gemini. Chrome, Google, DNS, sincronización y otros procesos pueden generar tráfico de fondo.
2. Un chat nuevo no implica una conexión TCP/TLS nueva. Las conexiones pueden reutilizarse entre prompts.
3. HTTPS cifra el contenido. No esperes ver el texto del prompt o la respuesta en claro en el PCAPNG.
4. La automatización puede cambiar el comportamiento del navegador. Mantén constantes perfil, versión, idioma, modelo, extensiones y condiciones de red.
5. El script es una base de trabajo, no un selector universal: la UI de Gemini cambia. Verifica selectores y extracción de respuesta antes de un lote.
6. Antes del experimento definitivo, decide si cada repetición debe usar un perfil limpio o un perfil persistente. No mezcles estrategias entre sesiones.
7. El script registra los bytes UTF-8 del prompt como `prompt_utf8_bytes`; esto no es lo mismo que los bytes de subida medidos en el PCAP.

## Seguridad y privacidad

El perfil `browser_profile` contiene cookies y tokens de sesión. No lo compartas ni lo subas a GitHub. Añade `browser_profile/`, `captures/` y `config.json` a `.gitignore`.
