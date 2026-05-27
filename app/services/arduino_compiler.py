"""
============================================================
arduino_compiler.py - Servicio de compilación segura Arduino
============================================================

Compila sketches Arduino usando arduino-cli de forma segura.

SEGURIDAD:
- subprocess.run() con lista de argumentos (NUNCA shell=True)
- Nombres de archivo ya validados por Pydantic (regex estricta)
- Paths generados internamente con pathlib (sin input del usuario)
- FQBN validado contra allowlist antes de llegar aquí
- Tempdir efímero se destruye automáticamente
- Timeout de 120 segundos por compilación
- No se usa shlex.quote() porque NO usamos shell=True;
  la lista de args es la forma más segura posible.

Referencia: https://docs.python.org/3/library/subprocess.html#security-considerations
"""

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
import base64
from pathlib import Path
from typing import Optional

logger = logging.getLogger("arduino_compiler")

# ----------------------------------------------------------
# Boards soportados (allowlist cerrada)
# ----------------------------------------------------------
ALLOWED_BOARDS: dict[str, dict] = {
    "arduino:avr:uno":        {"name": "Arduino Uno",       "variant": "uno"},
    "arduino:avr:nano":       {"name": "Arduino Nano",      "variant": "uno"},
    "arduino:avr:mega":       {"name": "Arduino Mega 2560", "variant": "mega"},
    "arduino:avr:leonardo":   {"name": "Arduino Leonardo",  "variant": "uno"},
    "arduino:avr:micro":      {"name": "Arduino Micro",     "variant": "uno"},
    # ESP32
    "esp32:esp32:esp32":      {"name": "ESP32 (Clásico)",   "variant": "esp32"},
    "esp32:esp32:esp32:FlashSize=4M,FlashMode=dio": {
        "name": "ESP32 Dev Module (4MB/DIO)", 
        "variant": "esp32"
    },
    "esp32:esp32:esp32s3":    {"name": "ESP32-S3",          "variant": "esp32s3"},
    "esp32:esp32:esp32c3":    {"name": "ESP32-C3 (RISC-V)", "variant": "esp32c3"}
}

# ----------------------------------------------------------
# Bibliotecas permitidas (allowlist cerrada)
# Clave = nombre de display, valor = nombre exacto para arduino-cli
# ----------------------------------------------------------
ALLOWED_LIBRARIES: dict[str, str] = {
    # Sensores
    "DHT sensor library":        "DHT sensor library",
    "Adafruit Unified Sensor":   "Adafruit Unified Sensor",
    "OneWire":                   "OneWire",
    "DallasTemperature":         "DallasTemperature",
    "HCSR04":                    "HCSR04",
    # Pantallas / gráficos
    "Adafruit GFX Library":      "Adafruit GFX Library",
    "Adafruit ILI9341":          "Adafruit ILI9341",
    "Adafruit SSD1306":          "Adafruit SSD1306",
    "Adafruit ST7735 and ST7789 Library": "Adafruit ST7735 and ST7789 Library",
    "U8g2":                      "U8g2",
    # I2C / LCD
    "LiquidCrystal I2C":         "LiquidCrystal I2C",
    "Adafruit BusIO":            "Adafruit BusIO",
    # Servos / motores
    "Servo":                     "Servo",
    "Stepper":                   "Stepper",
    "AccelStepper":              "AccelStepper",
    # Almacenamiento
    "SD":                        "SD",
    # Comunicación
    "IRremote":                  "IRremote",
    "PubSubClient":              "PubSubClient",
    "ArduinoJson":               "ArduinoJson",
    # LEDs
    "FastLED":                   "FastLED",
    "Adafruit NeoPixel":         "Adafruit NeoPixel",
    # Teclado / Keypad
    "Keypad":                    "Keypad",
    # Tiempo / RTC
    "RTClib":                    "RTClib",
    "TimeLib":                   "Time",
}

# Categorías para mostrar en la UI
LIBRARY_CATEGORIES: dict[str, list[str]] = {
    "Sensores":           ["DHT sensor library", "Adafruit Unified Sensor", "OneWire",
                           "DallasTemperature", "HCSR04"],
    "Pantallas":          ["Adafruit GFX Library", "Adafruit ILI9341", "Adafruit SSD1306",
                           "Adafruit ST7735 and ST7789 Library", "U8g2"],
    "I2C / LCD":          ["LiquidCrystal I2C", "Adafruit BusIO"],
    "Motores / Servos":   ["Servo", "Stepper", "AccelStepper"],
    "Almacenamiento":     ["SD"],
    "Comunicación":       ["IRremote", "PubSubClient", "ArduinoJson"],
    "LEDs":               ["FastLED", "Adafruit NeoPixel"],
    "Otros":              ["Keypad", "RTClib", "TimeLib"],
}

# Cache en memoria: bibliotecas ya instaladas en este proceso del servidor
_installed_libs: set[str] = set()
_install_lock = asyncio.Lock()

# Timeout máximo de compilación (segundos)
COMPILE_TIMEOUT = 120

# Timeout máximo de instalación de bibliotecas (segundos)
INSTALL_TIMEOUT = 90

# Regex para parsear uso de memoria del stdout de arduino-cli
# Ejemplo: "Sketch uses 924 bytes (2%) of program storage space. Maximum is 32256 bytes."
FLASH_RE = re.compile(
    r'Sketch uses (\d+) bytes \((\d+)%\) of program storage space\.\s*Maximum is (\d+) bytes',
    re.IGNORECASE,
)
# Ejemplo: "Global variables use 9 bytes (0%) of dynamic memory, leaving 2039 bytes for local variables. Maximum is 2048 bytes."
RAM_RE = re.compile(
    r'Global variables use (\d+) bytes \((\d+)%\) of dynamic memory.*?Maximum is (\d+) bytes',
    re.IGNORECASE | re.DOTALL,
)


class ArduinoCompilerService:
    """
    Servicio de compilación de sketches Arduino.
    
    Uso:
        compiler = ArduinoCompilerService()
        result = await compiler.compile(
            files=[{"name": "sketch.ino", "content": "void setup(){} void loop(){}"}],
            board_fqbn="arduino:avr:uno",
        )
    """

    def __init__(self):
        self.cli_path = shutil.which("arduino-cli") or "arduino-cli"
        self._verified = False

    async def verify_cli(self) -> dict:
        """Verificar que arduino-cli está disponible y funcional."""
        try:
            def _run():
                return subprocess.run(
                    [self.cli_path, "version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

            result = await asyncio.to_thread(_run)
            if result.returncode == 0:
                self._verified = True
                return {
                    "available": True,
                    "version": result.stdout.strip(),
                }
            return {"available": False, "error": result.stderr.strip()}
        except FileNotFoundError:
            return {"available": False, "error": "arduino-cli no encontrado en PATH"}
        except Exception as e:
            return {"available": False, "error": str(e)}

    def is_board_allowed(self, fqbn: str) -> bool:
        """Verificar si el FQBN está en la allowlist."""
        return fqbn in ALLOWED_BOARDS

    def get_allowed_boards(self) -> list[dict]:
        """Retornar lista de boards soportados."""
        return [
            {"fqbn": fqbn, **info}
            for fqbn, info in ALLOWED_BOARDS.items()
        ]

    def is_library_allowed(self, name: str) -> bool:
        """Verificar si la biblioteca está en la allowlist."""
        return name in ALLOWED_LIBRARIES

    def get_allowed_libraries(self) -> dict:
        """Retornar bibliotecas agrupadas por categoría."""
        return {
            cat: [
                {"name": lib, "installed": lib in _installed_libs}
                for lib in libs
                if lib in ALLOWED_LIBRARIES
            ]
            for cat, libs in LIBRARY_CATEGORIES.items()
        }

    async def populate_cache(self) -> None:
        """
        Consultar arduino-cli lib list al arrancar y poblar _installed_libs.
        Se llama una vez en el lifespan startup para que las compilaciones
        posteriores no incurran en overhead de instalación innecesaria.
        """
        global _installed_libs
        try:
            def _run():
                return subprocess.run(
                    [self.cli_path, "lib", "list"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            result = await asyncio.to_thread(_run)
            if result.returncode == 0:
                # Parsear líneas: "Name                    Installed  ..."
                new_cache: set[str] = set()
                for line in result.stdout.splitlines()[1:]:  # saltar header
                    parts = line.split()
                    if parts:
                        lib_name = parts[0]
                        # Buscar coincidencia con ALLOWED_LIBRARIES (case-insensitive)
                        for allowed in ALLOWED_LIBRARIES:
                            if allowed.lower() == lib_name.lower():
                                new_cache.add(allowed)
                                break
                _installed_libs = new_cache
                logger.info(f"Library cache populated: {len(_installed_libs)} libraries")
        except Exception as e:
            logger.warning(f"Could not populate library cache: {e}")

    async def install_libraries(self, libraries: list[str]) -> dict:
        """
        Instalar las bibliotecas requeridas si no están ya en caché.

        Args:
            libraries: Nombres de bibliotecas (ya validados contra allowlist)

        Returns:
            dict con: installed, already_cached, errors, stdout
        """
        global _installed_libs

        already_cached = [lib for lib in libraries if lib in _installed_libs]
        to_install = [lib for lib in libraries if lib not in _installed_libs]

        if not to_install:
            return {
                "installed": [],
                "already_cached": already_cached,
                "errors": [],
                "stdout": "",
            }

        # Resolver nombres exactos para arduino-cli
        cli_names = [ALLOWED_LIBRARIES[lib] for lib in to_install]

        async with _install_lock:
            # Re-check inside lock (otro request pudo haber instalado mientras esperábamos)
            still_to_install = [lib for lib in to_install if lib not in _installed_libs]
            if not still_to_install:
                return {
                    "installed": [],
                    "already_cached": already_cached + to_install,
                    "errors": [],
                    "stdout": "",
                }

            cli_names = [ALLOWED_LIBRARIES[lib] for lib in still_to_install]
            # SEGURIDAD: lista de args, NUNCA shell=True
            cmd = [self.cli_path, "lib", "install"] + cli_names
            logger.info(f"Installing libraries: {cli_names}")

            try:
                def _run_install():
                    return subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=INSTALL_TIMEOUT,
                    )

                result = await asyncio.to_thread(_run_install)
                stdout = (result.stdout or "") + (result.stderr or "")

                if result.returncode == 0:
                    # Marcar como instaladas en caché
                    for lib in still_to_install:
                        _installed_libs.add(lib)
                    logger.info(f"Libraries installed successfully: {still_to_install}")
                    return {
                        "installed": still_to_install,
                        "already_cached": already_cached,
                        "errors": [],
                        "stdout": stdout,
                    }
                else:
                    logger.warning(f"Library install failed (rc={result.returncode}): {stdout}")
                    return {
                        "installed": [],
                        "already_cached": already_cached,
                        "errors": still_to_install,
                        "stdout": stdout,
                    }

            except subprocess.TimeoutExpired:
                logger.warning(f"Library install timed out after {INSTALL_TIMEOUT}s")
                return {
                    "installed": [],
                    "already_cached": already_cached,
                    "errors": still_to_install,
                    "stdout": f"Timeout instalando bibliotecas ({INSTALL_TIMEOUT}s)",
                }

    async def compile(
        self,
        files: list[dict],
        board_fqbn: str = "arduino:avr:uno",
        libraries: list[str] | None = None,
    ) -> dict:
        """
        Compilar un sketch Arduino.

        Args:
            files: Lista de {"name": str, "content": str}
            board_fqbn: FQBN del board target (ya validado contra allowlist)
            libraries: Nombres de bibliotecas a instalar antes de compilar

        Returns:
            dict con: success, hex_content, stdout, stderr, error,
                      flash_used, flash_total, ram_used, ram_total

        Seguridad:
            - Los archivos se escriben en un tempdir efímero
            - subprocess.run() usa lista de args (no shell)
            - Timeout de 120s
        """
        libraries = libraries or []
        lib_stdout = ""

        # ── Instalar bibliotecas si se requieren ──────────────────────────
        if libraries:
            logger.info(f"Installing {len(libraries)} libraries before compile: {libraries}")
            install_result = await self.install_libraries(libraries)
            lib_stdout = install_result.get("stdout", "")
            if install_result["errors"]:
                logger.warning(f"Some libraries failed to install: {install_result['errors']}")
                # No abortamos — seguimos compilando; el error de #include lo verá el usuario

        logger.info(f"Compilando sketch para {board_fqbn} ({len(files)} archivos)")

        with tempfile.TemporaryDirectory(prefix="arduino_compile_") as temp_dir:
            sketch_dir = Path(temp_dir) / "sketch"
            sketch_dir.mkdir()

            # ── Escribir archivos del sketch ──────────────────────────
            has_sketch_ino = any(f["name"] == "sketch.ino" for f in files)
            main_ino_written = False

            for file_entry in files:
                name: str = file_entry["name"]
                content: str = file_entry["content"]

                # Promover el primer .ino a sketch.ino si no hay uno explícito
                write_name = name
                if not has_sketch_ino and name.endswith(".ino") and not main_ino_written:
                    write_name = "sketch.ino"
                    main_ino_written = True

                file_path = sketch_dir / write_name
                file_path.write_text(content, encoding="utf-8")
                logger.debug(f"  Escribiendo {write_name} ({len(content)} bytes)")

            # Fallback: si no se envió ningún .ino
            if not any(f["name"].endswith(".ino") for f in files):
                fallback = sketch_dir / "sketch.ino"
                fallback.write_text(
                    "void setup(){}\nvoid loop(){}",
                    encoding="utf-8",
                )

            # ── Compilar ──────────────────────────────────────────────

            build_dir = sketch_dir / "build"
            build_dir.mkdir()
            if build_dir.exists():
                shutil.rmtree(build_dir)
            build_dir.mkdir(parents=True, exist_ok=True)
            # SEGURIDAD: lista de argumentos, NUNCA string + shell=True
            cmd = [
                self.cli_path,
                "compile",
                "--fqbn", board_fqbn,
                "--output-dir", str(build_dir),
                str(sketch_dir),
            ]

            logger.info(f"Ejecutando: {' '.join(cmd)}")

            try:
                def _run_compile():
                    return subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=COMPILE_TIMEOUT,
                        # ⚠️ NUNCA shell=True — esta es la defensa principal
                        # contra command injection. Al pasar una lista de args,
                        # el kernel ejecuta directamente sin intérprete de shell.
                    )

                result = await asyncio.to_thread(_run_compile)

            except subprocess.TimeoutExpired:
                logger.warning(f"Compilación excedió timeout de {COMPILE_TIMEOUT}s")
                return {
                    "success": False,
                    "hex_content": None,
                    "stdout": "",
                    "stderr": "",
                    "error": f"Compilación excedió el tiempo máximo ({COMPILE_TIMEOUT}s)",
                    "flash_used": None,
                    "flash_total": None,
                    "ram_used": None,
                    "ram_total": None,
                }
            except Exception as e:
                logger.error(f"Error ejecutando arduino-cli: {e}")
                return {
                    "success": False,
                    "hex_content": None,
                    "stdout": "",
                    "stderr": "",
                    "error": f"Error interno: {str(e)}",
                    "flash_used": None,
                    "flash_total": None,
                    "ram_used": None,
                    "ram_total": None,
                }

            # ── Parsear resultado ─────────────────────────────────────
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            combined = stdout + "\n" + stderr

            # Parsear uso de memoria
            flash_used, flash_total = self._parse_flash(combined)
            ram_used, ram_total = self._parse_ram(combined)

            if result.returncode != 0:
                logger.warning(f"Compilación falló (rc={result.returncode})")
                return {
                    "success": False,
                    "hex_content": None,
                    "stdout": (lib_stdout + "\n" + stdout).strip(),
                    "stderr": stderr,
                    "error": "Error de compilación",
                    "flash_used": flash_used,
                    "flash_total": flash_total,
                    "ram_used": ram_used,
                    "ram_total": ram_total,
                }

            # ── Buscar archivo .hex de salida ─────────────────────────
            # ── Buscar archivo de salida (.hex o .bin) ─────────────────
            is_esp32 = "esp32" or "esp32:FlashSize=4M,FlashMode=dio" in board_fqbn
            
            if is_esp32:
                # 1. Intentamos buscar el archivo de app con nombre genérico
                bin_file = build_dir / "sketch.ino.bin"
                
                # 2. Si no existe, buscamos el archivo real de la aplicación filtrando el resto
                if not bin_file.exists():
                    all_bins = list(build_dir.glob("*.bin"))
                    
                    # Filtramos: Queremos el .bin que NO sea bootloader, ni partitions, ni merged
                    app_files = [
                        f for f in all_bins 
                        if "bootloader" not in f.name 
                        and "partitions" not in f.name 
                        and "merged" not in f.name
                        and f.name != "sketch.ino.bin" # 👈 DESPRECIAMOS EL INTERMEDIO GENÉRICO
                
                    ]
                    
                    # Si encontramos el binario puro de la app, lo asignamos
                    if app_files:
                        bin_file = app_files[0]
                    else:
                    # Fallback solo si no hay otro:
                        bin_file = build_dir / "sketch.ino.bin"

                # 3. Procesamos el archivo correcto
                if bin_file and bin_file.exists():
                    logger.info(f"Enviando al frontend el binario de aplicación: {bin_file.name} ({bin_file.stat().st_size} bytes)")
                    raw_bytes = bin_file.read_bytes()
                    encoded_content = base64.b64encode(raw_bytes).decode('utf-8')
                    logger.info(f"Compilación ESP32 Exitosa: {len(raw_bytes)} bytes")
                    return {
                        "success": True,
                        "hex_content": None,
                        "bin_content": encoded_content,
                        "binary_type": "esp32", # Clave informativa para el frontend
                        "stdout": (lib_stdout + "\n" + stdout).strip(),
                        "stderr": stderr,
                        "error": None,
                        "flash_used": flash_used,
                        "flash_total": flash_total,
                        "ram_used": ram_used,
                        "ram_total": ram_total,
                    }
                    
            else:
                # Lógica original para Arduino AVR (.hex)
                hex_file = build_dir / "sketch.ino.hex"
                if not hex_file.exists():
                    hex_files = list(build_dir.glob("*.hex"))
                    hex_file = hex_files[0] if hex_files else None

                if hex_file and hex_file.exists():
                    hex_content = hex_file.read_text(encoding="utf-8")
                    logger.info(
                        f"Compilación exitosa: {len(hex_content)} bytes hex, "
                        f"Flash: {flash_used}/{flash_total}, RAM: {ram_used}/{ram_total}"
                    )
                    return {
                        "success": True,
                        "hex_content": hex_content,
                        "bin_content": None,
                        "stdout": (lib_stdout + "\n" + stdout).strip(),
                        "stderr": stderr,
                        "error": None,
                        "flash_used": flash_used,
                        "flash_total": flash_total,
                        "ram_used": ram_used,
                        "ram_total": ram_total,
                    }

            # Si llega aquí, no encontró ni .hex ni .bin
            logger.warning(f"Archivo compilado no encontrado en {build_dir}")
            return {
                "success": False,
                "hex_content": None,
                "bin_content": None,
                "stdout": (lib_stdout + "\n" + stdout).strip(),
                "stderr": stderr,
                "error": "Archivo binario/.hex no encontrado tras compilación",
                # ... (resto de las métricas)
            }
    # ── Helpers privados ──────────────────────────────────────────

    @staticmethod
    def _parse_flash(text: str) -> tuple[Optional[int], Optional[int]]:
        """Extraer uso de Flash del output del compilador."""
        m = FLASH_RE.search(text)
        if m:
            return int(m.group(1)), int(m.group(3))
        return None, None

    @staticmethod
    def _parse_ram(text: str) -> tuple[Optional[int], Optional[int]]:
        """Extraer uso de RAM del output del compilador."""
        m = RAM_RE.search(text)
        if m:
            return int(m.group(1)), int(m.group(3))
        return None, None


# Singleton del servicio
compiler_service = ArduinoCompilerService()
