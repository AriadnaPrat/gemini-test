# Gemini Browser Traffic Capture — WSL2

Automatización de Gemini Browser con Playwright y Python, captura de tráfico con Wireshark/dumpcap y generación de `meta.json`.

Esta guía está adaptada a **Ubuntu sobre WSL2**, utilizando WSLg para mostrar Chromium en una ventana visible.

---

## 1. Arquitectura

El experimento utiliza:

- **Python:** coordina cada sesión.
- **Playwright:** controla Chromium y la interfaz web de Gemini.
- **Chromium:** navegador visible en WSLg.
- **dumpcap:** captura el tráfico de red.
- **JSON:** registra los metadatos y las métricas temporales.

Cada prompt genera una carpeta independiente bajo `output_dir` (por defecto,
`captures/`). Puedes copiar las sesiones al drive manualmente:

```text
captures/
  20261103-171205_gemini_browser_T01a_r1/
    capture.pcapng
    keys.log
    dumpcap.log
    meta.json
```

`meta.json` sigue el contrato de `data_formats.md`. `response_type` es el
`expected_type` del CSV hasta que `groundtruth.json` (generado aparte) dé el
recuento de palabras. `dumpcap.log` guarda la salida de la captura.

`keys.log` contiene secretos TLS que permiten descifrar tráfico de la captura.
Se genera localmente junto a cada PCAP para análisis del capturador; **no lo
copies al drive ni lo compartas**.

## 2. Requisitos

En Windows:

- Windows 11 recomendado.
- WSL2 habilitado.
- WSLg disponible para aplicaciones gráficas.

En WSL:

- Ubuntu 22.04 o 24.04.
- Python 3.10 o superior.
- Playwright.
- Chromium.
- Wireshark/dumpcap.

Comprueba la versión de WSL desde PowerShell:

```powershell
wsl --version
wsl --status
```

Si todavía no tienes Ubuntu instalado:

```powershell
wsl --install -d Ubuntu-24.04
```

Reinicia Windows si lo solicita.

## 3. Instalar dependencias en Ubuntu

Abre Ubuntu desde Windows Terminal:

```bash
sudo apt update
sudo apt upgrade -y

sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    wireshark \
    tshark \
    tcpdump \
    libcap2-bin
```

Comprueba Python:

```bash
python3 --version
```

Comprueba dumpcap:

```bash
which dumpcap
dumpcap --version
```

Comprueba también tshark, que se usa para detectar si el PCAP contiene QUIC:

```bash
which tshark
tshark --version
```

Normalmente la ruta será:

```text
/usr/bin/dumpcap
```

## 4. Permitir capturas sin ejecutar todo el experimento como root

Configura los permisos de captura:

```bash
sudo dpkg-reconfigure wireshark-common
```

Cuando pregunte si los usuarios no privilegiados pueden capturar paquetes, selecciona:

```text
Yes
```

Añade tu usuario al grupo wireshark:

```bash
sudo usermod -aG wireshark "$USER"
```

Configura las capacidades de dumpcap:

```bash
sudo setcap cap_net_raw,cap_net_admin+eip "$(sudo which dumpcap)"
```

Cierra la terminal de Ubuntu y reinicia WSL desde PowerShell:

```powershell
wsl --shutdown
```

Abre Ubuntu otra vez.

Comprueba los grupos:

```bash
groups
```

Debe aparecer `wireshark`.

Comprueba las interfaces:

```bash
dumpcap -D
```

En WSL2 normalmente aparecerá una interfaz denominada `eth0`.

**Nota:** WSL2 utiliza una interfaz virtual. Esta captura no equivale necesariamente a capturar todo el tráfico desde la tarjeta Wi-Fi física de Windows. Si el protocolo requiere observar el tráfico en la interfaz física, habrá que configurar una captura en Windows y coordinarla desde WSL.

## 5. Preparar el proyecto

Es recomendable guardar el proyecto dentro del sistema de archivos Linux:

```bash
mkdir -p ~/gemini-playwright-capture
cd ~/gemini-playwright-capture
```

Copia aquí los archivos del proyecto y tu `prompts.csv`.

La estructura debe quedar así:

```text
gemini-playwright-capture/
├── run_experiment.py
├── inspect_gemini.py
├── requirements.txt
├── config.example.json
├── prompts.csv
├── captures/
└── browser_profile/
```

Evita trabajar directamente desde `/mnt/c` si no lo necesitas: el sistema de archivos nativo de WSL suele ofrecer mejor rendimiento.

## 6. Crear el entorno virtual de Python

Desde la carpeta del proyecto:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Actualiza pip:

```bash
python -m pip install --upgrade pip
```

Instala las dependencias:

```bash
pip install -r requirements.txt
```

Instala los navegadores de Playwright:

```bash
python -m playwright install --with-deps chromium
```

## 7. Configurar Chromium visible

En WSLg, Chromium puede abrirse en una ventana gráfica.

Comprueba que WSLg está disponible:

```bash
echo "$DISPLAY"
echo "$WAYLAND_DISPLAY"
```

Copia la configuración:

```bash
cp config.example.json config.json
```

Edita `config.json`:

```bash
nano config.json
```

Configura estos campos:

```json
{
  "gemini_url": "https://gemini.google.com/app",
  "browser_user_data_dir": "./browser_profile",
  "browser_channel": null,
  "headless": false,
  "model_name": "Flash-Lite",
  "dumpcap_path": "/usr/bin/dumpcap",
  "tshark_path": "/usr/bin/tshark",
  "interface": "eth0",
  "output_dir": "./captures",
  "csv_path": "./prompts.csv",
  "network": "unspecified",
  "netem": "none",
  "capturer": "unspecified",
  "repetition": 1,
  "limit": 1,
  "pause_for_manual_login": true
}
```

Con `browser_channel: null`, Playwright utiliza el Chromium que instala con su propio gestor de navegadores, en lugar de buscar Google Chrome instalado en Linux.

Con `headless: false`, el navegador se muestra en pantalla.

Con `limit: 1`, solo se ejecuta un prompt durante la primera prueba.

Con `interface: eth0`, dumpcap captura desde la interfaz de red virtual de WSL.

`output_dir` es un directorio local de preparación; copia las carpetas de sesión
al drive cuando quieras compartirlas. Rellena `network` y `capturer` con los
valores de la captura. `client_version` se obtiene del navegador y `quic` se
detecta leyendo el PCAP con tshark.

Conserva los demás campos de `selectors` y `timing` del archivo original.

## 8. Comprobar Chromium

Antes de ejecutar el experimento, prueba que Playwright puede abrir el navegador:

```bash
python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=False); page=b.new_page(); page.goto('https://gemini.google.com/app'); input('Pulsa ENTER para cerrar...'); b.close(); p.stop()"
```

Debe abrirse una ventana de Chromium.

Si no aparece, revisa WSLg y sus variables gráficas.

## 9. Inspeccionar la interfaz de Gemini

Ejecuta:

```bash
python3 inspect_gemini.py
```

El inspector reutiliza `browser_user_data_dir` de `config.json`, igual que el experimento. Inicia sesión si hace falta y comprueba los elementos que imprime.

Es necesario verificar los selectores de:

- Botón de nuevo chat.
- Campo de entrada del prompt.
- Botón de envío.
- Contenedor de respuesta.
- Indicador de generación.

La interfaz de Gemini puede cambiar y los selectores del ejemplo son provisionales.

**No ejecutes los 60 prompts hasta verificar que la automatización envía el texto correcto y recoge la respuesta completa.**

## 10. Primera prueba de captura

Comprueba primero que dumpcap puede capturar:

```bash
dumpcap -D
```

Después ejecuta:

```bash
python run_experiment.py --config config.json --limit 1
```

La primera ejecución:

1. Abre Chromium.
2. Permite iniciar sesión manualmente en Gemini.
3. Espera a que pulses ENTER en la terminal; si Gemini todavía muestra `Sign in`, vuelve a pedirlo y no empieza la sesión.
4. Abre un chat nuevo.
5. Envía el primer prompt haciendo clic en el botón configurado (también reconoce etiquetas comunes en español y catalán). Si no encuentra un botón visible y habilitado, falla sin enviar el prompt con ENTER.
6. Espera a que termine la respuesta.
7. Detiene la captura.
8. Genera `meta.json`.

Comprueba que la carpeta de salida contiene:

```text
capture.pcapng
keys.log
dumpcap.log
meta.json
```

Abre el PCAPNG con Wireshark para comprobar que contiene paquetes.

## 11. Ejecutar los 60 prompts

Una vez validada la prueba individual, modifica:

```json
"limit": 1
```

a:

```json
"limit": 0
```

Después ejecuta:

```bash
python run_experiment.py --config config.json
```

Para empezar desde el prompt número 21:

```bash
python run_experiment.py --config config.json --start-row 21
```

El script lee el CSV y procesa cada prompt de manera secuencial.

## 12. Etiquetado de respuestas

El script no cuenta palabras: `response_type` en `meta.json` es el
`expected_type` del CSV. La etiqueta definitiva (`short`/`long`) se obtiene más
tarde a partir del recuento de palabras de `groundtruth.json`.

## 13. Consideraciones metodológicas

1. Un PCAPNG por sesión facilita la asociación entre prompt, respuesta y captura.
2. La captura de `eth0` puede incluir tráfico de fondo de WSL.
3. Un chat nuevo no implica necesariamente una nueva conexión TCP/TLS.
4. HTTPS cifra el contenido de los prompts y las respuestas.
5. El tamaño de `prompt_utf8_bytes` no representa el tamaño real de la petición HTTP.
6. Mantén constantes el modelo, navegador, perfil, idioma, condiciones de red y configuración.
7. Registra los errores de automatización y no consideres válidas las sesiones incompletas.
8. No mezcles capturas realizadas desde Windows y WSL sin documentar las diferencias.

## 14. Privacidad

El directorio `browser_profile/` contiene cookies y datos de autenticación de Gemini.

No lo compartas ni lo subas a GitHub.

Añade estas rutas a `.gitignore`:

```text
.venv/
browser_profile/
captures/
config.json
__pycache__/
```

---

**Primera meta:** conseguir una sesión completa con Chromium visible, un PCAPNG válido, `keys.log` y `meta.json` correctos antes de ejecutar el lote de 60 prompts.
