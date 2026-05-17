"""
============================================================
content_scanner.py - Escaneo del Filesystem para Poblar Cursos
============================================================

Este servicio analiza la estructura de carpetas del workspace
y crea automáticamente los cursos, módulos y lecciones en la BD.

¿Por qué automatizarlo?
- El workspace tiene ~100 módulos con ~300+ archivos
- Crear todo manualmente sería tedioso y propenso a errores
- Al actualizar el contenido, solo se re-escanea
- Garantiza consistencia entre filesystem y BD

Estructura esperada del filesystem:
    ProjectBlockchain/           → Course (slug: "blockchain-cpp")
    ├── es/                     → Contenido en español (idioma principal)
    │   ├── 01_hashing/         → Module (order: 1)
    │   │   ├── README.md       → Lesson (type: "theory")
    │   │   └── src/sha256.c    → Lesson (type: "code")
    │   └── 02_block/           → Module (order: 2)
    └── en/                     → Contenido en inglés (opcional)
        ├── 01_hashing/
        └── 02_block/

El scanner escanea desde la subcarpeta es/ (idioma base).
La subcarpeta en/ se usa en runtime para servir contenido traducido
con fallback a es/ si el archivo no existe en inglés.

Convención de slugs:
- course slug: derivado del nombre del proyecto (ej: "blockchain-cpp")
- module slug: nombre de la carpeta limpiado (ej: "01-hashing")
- lesson slug: nombre del archivo limpiado (ej: "readme", "sha256-c")
"""

import os
import re
from typing import List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.course import Course, Module, Lesson


# ----------------------------------------------------------
# Definición de cursos predeterminados
# ----------------------------------------------------------
# Esta estructura define los 7 cursos iniciales con su metadata.
# source_path es relativo a CONTENT_BASE_PATH.
PREDEFINED_COURSES = [
    {
        "title": "Blockchain Engineering en C/C++",
        "slug": "blockchain-cpp",
        "description": (
            "Curso completo de ingeniería blockchain desde cero. "
            "Implementa SHA-256, bloques, proof of work, árboles Merkle, "
            "firmas digitales ECDSA, networking P2P con epoll, consenso "
            "y proyectos integradores (MiniCoin, voto descentralizado, "
            "supply chain). 15 módulos + 3 proyectos."
        ),
        "short_description": (
            "Construye una blockchain completa desde cero en C/C++: "
            "criptografía, networking, consenso y proyectos reales."
        ),
        "title_en": "Blockchain Engineering in C/C++",
        "description_en": (
            "Complete blockchain engineering course from scratch. "
            "Implement SHA-256, blocks, proof of work, Merkle trees, "
            "ECDSA digital signatures, P2P networking with epoll, consensus "
            "and integrating projects (MiniCoin, decentralized voting, "
            "supply chain). 15 modules + 3 projects."
        ),
        "short_description_en": (
            "Build a complete blockchain from scratch in C/C++: "
            "cryptography, networking, consensus and real projects."
        ),
        "language": "C/C++",
        "difficulty": "advanced",
        "estimated_hours": 80,
        "price": 49.99,
        "price_usd": 49.99,
        "source_path": "ProjectBlockchain",
        "image_url": "/images/courses/blockchain.png",
    },
    {
        "title": "Linux Systems Programming - Stack TCP/IP en C",
        "slug": "tcp-ip-linux-c",
        "description": (
            "Domina la programación de sistemas Linux con C puro. "
            "Sockets TCP/UDP, concurrencia con fork/pthreads, "
            "multiplexación con epoll, IPC (pipes, message queues), "
            "shared memory con mmap, zero-copy con sendfile/splice, "
            "y desarrollo de drivers del kernel."
        ),
        "short_description": (
            "Programación de sistemas Linux desde sockets TCP hasta "
            "kernel modules. 8 módulos progresivos en C puro."
        ),
        "title_en": "Linux Systems Programming - TCP/IP Stack in C",
        "description_en": (
            "Master Linux systems programming with pure C. "
            "TCP/UDP sockets, concurrency with fork/pthreads, "
            "multiplexing with epoll, IPC (pipes, message queues), "
            "shared memory with mmap, zero-copy with sendfile/splice, "
            "and kernel driver development."
        ),
        "short_description_en": (
            "Linux systems programming from TCP sockets to "
            "kernel modules. 8 progressive modules in pure C."
        ),
        "language": "C",
        "difficulty": "intermediate",
        "estimated_hours": 60,
        "price": 39.99,
        "price_usd": 39.99,
        "source_path": "ProjectCpp",
        "image_url": "/images/courses/tcp-linux.png",
    },
    {
        "title": "Computer Vision con OpenCV y Deep Learning",
        "slug": "computer-vision",
        "description": (
            "Curso integral de visión por computadora. Desde fundamentos "
            "de imagen hasta deep learning con PyTorch. Dual: C++ y Python. "
            "OpenCV, filtros, segmentación, SIFT/ORB, calibración de cámara, "
            "flujo óptico, YOLO/SSD, transfer learning, visión estéreo, "
            "reconstrucción 3D e integración con ROS2."
        ),
        "short_description": (
            "Visión por computadora completa: OpenCV + PyTorch en C++ y Python. "
            "17 módulos desde imagen básica hasta deep learning."
        ),
        "title_en": "Computer Vision with OpenCV and Deep Learning",
        "description_en": (
            "Comprehensive computer vision course. From image fundamentals "
            "to deep learning with PyTorch. Dual: C++ and Python. "
            "OpenCV, filters, segmentation, SIFT/ORB, camera calibration, "
            "optical flow, YOLO/SSD, transfer learning, stereo vision, "
            "3D reconstruction and ROS2 integration."
        ),
        "short_description_en": (
            "Complete computer vision: OpenCV + PyTorch in C++ and Python. "
            "17 modules from basic imaging to deep learning."
        ),
        "language": "C++/Python",
        "difficulty": "intermediate",
        "estimated_hours": 100,
        "price": 59.99,
        "price_usd": 59.99,
        "source_path": "ProjectCv",
        "image_url": "/images/courses/computer-vision.png",
    },
    {
        "title": "ESP32 - Firmware IoT con ESP-IDF y FreeRTOS",
        "slug": "esp32-firmware",
        "description": (
            "Desarrollo de firmware para ESP32 con ESP-IDF. "
            "GPIO, timers, PWM, UART, I2C, SPI, ADC, WiFi, MQTT, "
            "NVS storage, HTTP, WebSocket, FreeRTOS avanzado "
            "(semáforos, colas, event groups), PID, OTA, deep sleep."
        ),
        "short_description": (
            "Firmware IoT profesional con ESP32: desde blink LED hasta "
            "OTA updates y control PID. 22 módulos."
        ),
        "title_en": "ESP32 - IoT Firmware with ESP-IDF and FreeRTOS",
        "description_en": (
            "ESP32 firmware development with ESP-IDF. "
            "GPIO, timers, PWM, UART, I2C, SPI, ADC, WiFi, MQTT, "
            "NVS storage, HTTP, WebSocket, advanced FreeRTOS "
            "(semaphores, queues, event groups), PID, OTA, deep sleep."
        ),
        "short_description_en": (
            "Professional IoT firmware with ESP32: from blink LED to "
            "OTA updates and PID control. 22 modules."
        ),
        "language": "C (ESP-IDF)",
        "difficulty": "intermediate",
        "estimated_hours": 70,
        "price": 44.99,
        "price_usd": 44.99,
        "source_path": "ProjectEsp32",
        "image_url": "/images/courses/esp32.png",
    },
    {
        "title": "STM32 - De C a Firmware Engineer",
        "slug": "stm32-firmware",
        "description": (
            "Ruta completa desde fundamentos de C hasta firmware profesional "
            "en STM32F411. Fundamentos de C, Linux systems, build systems, "
            "embedded foundations (bitwise, registros, interrupciones), "
            "HAL (GPIO, UART, Timers, ADC, DMA), FreeRTOS, "
            "drivers (SPI, I2C), procesamiento de señales."
        ),
        "short_description": (
            "De programador C a firmware engineer: STM32F411 con HAL, "
            "FreeRTOS, drivers y DSP. 9 módulos intensivos."
        ),
        "title_en": "STM32 - From C to Firmware Engineer",
        "description_en": (
            "Complete path from C fundamentals to professional firmware "
            "on STM32F411. C fundamentals, Linux systems, build systems, "
            "embedded foundations (bitwise, registers, interrupts), "
            "HAL (GPIO, UART, Timers, ADC, DMA), FreeRTOS, "
            "drivers (SPI, I2C), signal processing."
        ),
        "short_description_en": (
            "From C programmer to firmware engineer: STM32F411 with HAL, "
            "FreeRTOS, drivers and DSP. 9 intensive modules."
        ),
        "language": "C/C++",
        "difficulty": "intermediate",
        "estimated_hours": 90,
        "price": 54.99,
        "price_usd": 54.99,
        "source_path": "ProjectStm32",
        "image_url": "/images/courses/stm32.png",
    },
    {
        "title": "Raspberry Pi - Systems Engineering en C",
        "slug": "raspberry-pi-systems",
        "description": (
            "Ingeniería de sistemas en Raspberry Pi con C. "
            "File I/O, procesos, hilos POSIX, IPC, sockets TCP/UDP, "
            "multiplexación, shared memory, GPIO con libgpiod, "
            "SPI, I2C, y DSP con filtros FIR/IIR. "
            "Incluye 3 proyectos integradores."
        ),
        "short_description": (
            "Programación de sistemas en Raspberry Pi: POSIX, "
            "sockets, GPIO y DSP. 10 módulos + 3 proyectos."
        ),
        "title_en": "Raspberry Pi - Systems Engineering in C",
        "description_en": (
            "Systems engineering on Raspberry Pi with C. "
            "File I/O, processes, POSIX threads, IPC, TCP/UDP sockets, "
            "multiplexing, shared memory, GPIO with libgpiod, "
            "SPI, I2C, and DSP with FIR/IIR filters. "
            "Includes 3 integrating projects."
        ),
        "short_description_en": (
            "Systems programming on Raspberry Pi: POSIX, "
            "sockets, GPIO and DSP. 10 modules + 3 projects."
        ),
        "language": "C/C++",
        "difficulty": "intermediate",
        "estimated_hours": 65,
        "price": 39.99,
        "price_usd": 39.99,
        "source_path": "ProjectRpi",
        "image_url": "/images/courses/raspberry-pi.png",
    },
    {
        "title": "FPGA con VHDL - Tang Nano 20K",
        "slug": "fpga-vhdl",
        "description": (
            "Diseño digital con VHDL para la FPGA Sipeed Tang Nano 20K. "
            "Lógica combinacional (gates, MUX, ALU), secuencial "
            "(flip-flops, contadores, FSM), periféricos (debounce, PWM, UART). "
            "Proyectos: semáforo FSM, generador VGA, controlador SPI industrial."
        ),
        "short_description": (
            "Diseño digital con VHDL y FPGA Tang Nano 20K: "
            "de compuertas a proyectos industriales. 4 módulos + 3 proyectos."
        ),
        "title_en": "FPGA with VHDL - Tang Nano 20K",
        "description_en": (
            "Digital design with VHDL for the Sipeed Tang Nano 20K FPGA. "
            "Combinational logic (gates, MUX, ALU), sequential "
            "(flip-flops, counters, FSM), peripherals (debounce, PWM, UART). "
            "Projects: traffic light FSM, VGA generator, industrial SPI controller."
        ),
        "short_description_en": (
            "Digital design with VHDL and FPGA Tang Nano 20K: "
            "from gates to industrial projects. 4 modules + 3 projects."
        ),
        "language": "VHDL",
        "difficulty": "intermediate",
        "estimated_hours": 50,
        "price": 44.99,
        "price_usd": 44.99,
        "source_path": "ProjectFPGA",
        "image_url": "/images/courses/fpga.png",
    },
    {
        "title": "Arduino desde Cero: Introducción Práctica",
        "slug": "arduino-intro",
        "description": (
            "Tutorial diseñado para personas sin experiencia en programación "
            "ni electrónica. Aprende a controlar microcontroladores con Arduino "
            "usando C/C++ de forma progresiva y práctica. Fundamentos digitales, "
            "entrada digital con botones, salida analógica PWM, entrada analógica "
            "con sensores y comunicación serial."
        ),
        "short_description": (
            "Primeros pasos con Arduino: LEDs, botones, PWM y sensores. "
            "Curso introductorio práctico desde cero."
        ),
        "title_en": "Arduino from Scratch: Practical Introduction",
        "description_en": (
            "Tutorial designed for people with no programming or electronics "
            "experience. Learn to control microcontrollers with Arduino "
            "using C/C++ progressively and practically. Digital fundamentals, "
            "digital input with buttons, analog PWM output, analog input "
            "with sensors and serial communication."
        ),
        "short_description_en": (
            "First steps with Arduino: LEDs, buttons, PWM and sensors. "
            "Practical introductory course from scratch."
        ),
        "language": "C/C++ (Arduino)",
        "difficulty": "beginner",
        "estimated_hours": 10,
        "price": 0.0,
        "price_usd": 0.0,
        "source_path": "ProjectIntro",
        "image_url": "/images/courses/arduino-intro.png",
    },
]


def slugify(name: str) -> str:
    """
    Convierte un nombre de carpeta/archivo en un slug URL-safe.
    
    Ejemplos:
    - "01_hashing" → "01-hashing"
    - "README.md"  → "readme"
    - "sha256.c"   → "sha256-c"
    """
    # Quitar extensión
    name = os.path.splitext(name)[0]
    # Convertir a minúsculas
    name = name.lower()
    # Reemplazar _ y espacios por -
    name = re.sub(r"[_\s]+", "-", name)
    # Quitar caracteres no alfanuméricos excepto -
    name = re.sub(r"[^a-z0-9\-]", "", name)
    # Quitar guiones duplicados
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def is_content_file(filename: str) -> bool:
    """
    Determina si un archivo es contenido servible (markdown o código).
    """
    content_extensions = {
        ".md", ".c", ".h", ".cpp", ".hpp", ".cc",
        ".py", ".vhd", ".vhdl", ".v", ".sv",
        ".sh", ".cmake", ".ino",
        ".rs", ".js", ".ts", ".json",
        ".yaml", ".yml", ".toml", ".mk",
    }
    _, ext = os.path.splitext(filename)
    return ext.lower() in content_extensions


# Subdirectorios que nunca se escanean como lecciones de código
_CODE_SCAN_SKIP = {
    "build", ".git", "__pycache__", "common", "utils",
    "assets", "libro", "book", ".venv", "node_modules", "docs",
    "es", "en",  # Subcarpetas de idioma (no son módulos)
}


def resolve_course_content_path(
    source_path: str,
    lang: str = "es",
) -> str:
    """
    Resuelve la ruta al directorio de contenido de un curso para un idioma.

    Estructura esperada:
        CONTENT_BASE_PATH / source_path / lang / ...

    Si la subcarpeta del idioma no existe, intenta fallback a 'es'.
    Si tampoco existe 'es/', usa la raíz del source_path (compatibilidad
    con cursos que aún no migraron a la estructura es/en).

    Args:
        source_path: Carpeta relativa al CONTENT_BASE_PATH (ej: "ProjectBlockchain")
        lang: Código de idioma ("es" o "en")
    Returns:
        Ruta absoluta al directorio de contenido.
    """
    base = os.path.join(settings.CONTENT_BASE_PATH, source_path)
    preferred = os.path.join(base, lang)
    if os.path.isdir(preferred):
        return preferred
    # Fallback al idioma por defecto
    fallback = os.path.join(base, settings.DEFAULT_CONTENT_LANG)
    if os.path.isdir(fallback):
        return fallback
    # Compatibilidad: carpeta sin subdirectorio de idioma
    return base

# Nombres de los directorios fijos (para excluirlos del descubrimiento dinámico)
_FIXED_CODE_DIRS = {"src", "cpp", "python", "exercises"}


def _get_code_dirs(module_path: str) -> list:
    """
    Retorna la lista de subdirectorios a escanear dentro de un módulo.

    Combina los directorios fijos (src, cpp, python, ., exercises) con
    cualquier subdirectorio adicional descubierto dinámicamente.

    Esto permite indexar carpetas de sketches Arduino (minimo/,
    hello_serial/) o cualquier otra carpeta de código específica del
    proyecto, sin necesidad de listarlas manualmente.

    Ejemplo para 01_hello_world/:
        ["src", "cpp", "python", ".", "exercises",
         "hello_serial", "minimo"]   ← descubiertos automáticamente
    """
    dirs = ["src", "cpp", "python", ".", "exercises"]
    try:
        extra = sorted(
            d for d in os.listdir(module_path)
            if os.path.isdir(os.path.join(module_path, d))
            and not d.startswith(".")
            and d not in _CODE_SCAN_SKIP
            and d not in _FIXED_CODE_DIRS
        )
        dirs = dirs + extra
    except OSError:
        pass
    return dirs


def get_lesson_type(filename: str) -> str:
    """
    Determina el tipo de lección según la extensión del archivo.
    """
    if filename.lower().endswith(".md"):
        return "theory"
    return "code"


# ----------------------------------------------------------
# Metadata de archivos: idioma, tamaño, líneas
# ----------------------------------------------------------
_EXT_LANGUAGE_MAP = {
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".ino": "cpp",
    ".py": "python",
    ".vhd": "vhdl", ".vhdl": "vhdl",
    ".v": "verilog", ".sv": "systemverilog",
    ".sh": "bash",
    ".mk": "make", ".cmake": "cmake",
    ".rs": "rust",
    ".js": "javascript", ".ts": "typescript",
    ".json": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
}


def detect_language(filename: str) -> str | None:
    """
    Detecta el lenguaje de programación según la extensión del archivo.

    Retorna un string como "c", "cpp", "python", "markdown", etc.
    o None si la extensión no es reconocida.
    """
    ext = os.path.splitext(filename)[1].lower()
    return _EXT_LANGUAGE_MAP.get(ext)


def _file_meta(full_path: str, filename: str) -> dict:
    """
    Calcula metadata de un archivo: tamaño, número de líneas y lenguaje.

    Se usa durante el scan para popular las columnas size_bytes,
    line_count y language de cada Lesson.

    Args:
        full_path: Ruta absoluta al archivo.
        filename:  Nombre base del archivo (para detectar lenguaje).
    Returns:
        Dict con keys: size_bytes, line_count, language.
    """
    meta: dict = {"language": detect_language(filename)}
    try:
        meta["size_bytes"] = os.path.getsize(full_path)
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            meta["line_count"] = sum(1 for _ in f)
    except OSError:
        meta["size_bytes"] = None
        meta["line_count"] = None
    return meta


def _make_lesson(module_path: str, **kwargs) -> Lesson:
    """
    Crea un objeto Lesson con metadata de archivo calculada automáticamente.

    Calcula size_bytes, line_count y language a partir del archivo real
    en el filesystem y los inyecta en el constructor de Lesson.

    Args:
        module_path: Ruta absoluta al directorio del módulo.
        **kwargs:    Todos los campos normales de Lesson.
    Returns:
        Instancia de Lesson con metadata populada.
    """
    content_path = kwargs["content_path"]
    full_path = os.path.join(module_path, content_path)
    meta = _file_meta(full_path, os.path.basename(content_path))
    return Lesson(**kwargs, **meta)


def scan_numbered_md_files(module_dir: str) -> list:
    """
    Retorna la lista ordenada de archivos .md numerados dentro de un módulo.

    Convención esperada: NN[_-]nombre.md  (ej: 01_intro.md, 02-conceptos.md)
    El usuario puede dividir manualmente un README.md grande en estos archivos.

    Si existen archivos con este patrón se usan como lecciones individuales
    y el README.md del módulo es ignorado por el scanner.

    Ejemplos:
        01_intro.md            → lección 1
        02_implementacion.md   → lección 2
        03_ejercicios.md       → lección 3
    """
    pattern = re.compile(r"^\d{2,}[_\-].+\.md$")
    try:
        files = [
            f for f in os.listdir(module_dir)
            if os.path.isfile(os.path.join(module_dir, f)) and pattern.match(f)
        ]
    except OSError:
        return []
    return sorted(files)   # orden lexicográfico = numérico si están zero-padded


def humanize_title(name: str) -> str:
    """
    Convierte un nombre de carpeta/archivo en un título legible.

    Ejemplos:
    - "01_hashing" → "01 - Hashing"
    - "sha256.c" → "sha256.c"
    - "03_fourier" → "03 - Fourier"
    """
    # Quitar extensión para carpetas
    base = os.path.splitext(name)[0] if "." in name else name
    # Separar número de prefijo si existe
    match = re.match(r"^(\d+)[_\-](.+)$", base)
    if match:
        num, rest = match.groups()
        # Capitalizar cada palabra
        title_part = rest.replace("_", " ").replace("-", " ").title()
        return f"{num} - {title_part}"
    return base.replace("_", " ").replace("-", " ").title()


def _find_en_module_dir(course_base_path: str, es_module_name: str) -> str | None:
    """
    Busca el directorio correspondiente en en/ para un módulo escaneado desde es/.

    Estrategia:
    1. Coincidencia exacta: en/{es_module_name}
    2. Coincidencia por prefijo numérico: primer dir en en/ que empiece con el mismo número

    Args:
        course_base_path: Ruta absoluta a la carpeta raíz del curso (ej: /path/ProjectIntro)
        es_module_name:   Nombre de la carpeta del módulo en es/ (ej: "01_Fundamentos")
    Returns:
        Nombre del directorio en en/ (no la ruta completa), o None si no se encuentra.
    """
    en_dir = os.path.join(course_base_path, "en")
    if not os.path.isdir(en_dir):
        return None
    # Coincidencia exacta
    if os.path.isdir(os.path.join(en_dir, es_module_name)):
        return es_module_name
    # Coincidencia por prefijo numérico
    num_match = re.match(r'^(\d+)', es_module_name)
    if num_match:
        prefix = num_match.group(1)
        try:
            for entry in sorted(os.listdir(en_dir)):
                if entry.startswith(prefix) and os.path.isdir(os.path.join(en_dir, entry)):
                    return entry
        except OSError:
            pass
    return None


def _find_en_lesson_title(
    course_base_path: str,
    en_module_name: str,
    content_filename: str,
) -> str | None:
    """
    Deriva el title_en de una lección desde la carpeta en/.

    Para archivos .md numerados, busca el archivo con el mismo nombre en en/.
    Si existe, usa humanize_title sobre el nombre del archivo.
    Para README.md y archivos de código, usa humanize_title del en_module_name.

    Args:
        course_base_path:  Ruta absoluta al curso (ej: /path/ProjectIntro)
        en_module_name:    Nombre del directorio en en/ (ej: "01_Basics")
        content_filename:  Nombre del archivo de lección (ej: "03_Primer_programa.md")
    Returns:
        Título en inglés o None si no se puede determinar.
    """
    if not en_module_name:
        return None
    # Para archivos .md numerados, si existe el mismo archivo en en/ → humanize de él
    if re.match(r'^\d{2,}[_\-].+\.md$', content_filename):
        en_file = os.path.join(course_base_path, "en", en_module_name, content_filename)
        if os.path.exists(en_file):
            return humanize_title(content_filename)
        # El archivo en/ puede tener nombre distinto pero mismo número
        num_match = re.match(r'^(\d+)', content_filename)
        if num_match:
            prefix = num_match.group(1)
            en_mod_path = os.path.join(course_base_path, "en", en_module_name)
            try:
                for f in sorted(os.listdir(en_mod_path)):
                    if f.startswith(prefix) and f.endswith('.md'):
                        return humanize_title(f)
            except OSError:
                pass
    # Para README.md y archivos de código: title_en es el título del módulo en inglés
    return humanize_title(en_module_name)


async def rescan_module_lessons(module_id: int, db: AsyncSession) -> Dict[str, Any]:
    """
    Re-escanea el filesystem para un módulo existente y hace UPSERT de lecciones.

    Algoritmo:
    1. Carga el módulo y su curso desde la BD.
    2. Lista los archivos del directorio del módulo.
    3. Para cada archivo que debería ser una lección:
       - Si ya existe una Lesson con ese slug → actualiza content_path y metadata.
       - Si no existe → la crea (INSERT).
    4. NO borra lecciones que ya no están en el filesystem (para preservar progreso).
       Las lecciones huérfanas quedan pero el contenido dará 404 al cargar.

    Args:
        module_id: ID del módulo en BD.
        db: Sesión async de SQLAlchemy.
    Returns:
        {"added": int, "updated": int, "module_id": int, "module_slug": str}
    Raises:
        ValueError: Si el módulo no existe o la carpeta del filesystem no se encuentra.
    """
    from sqlalchemy.orm import selectinload

    # Cargar módulo + curso
    result = await db.execute(
        select(Module)
        .options(selectinload(Module.lessons), selectinload(Module.course))
        .where(Module.id == module_id)
    )
    module = result.scalar_one_or_none()
    if not module:
        raise ValueError(f"Módulo {module_id} no encontrado en BD")

    course = module.course
    course_content_path = resolve_course_content_path(course.source_path, "es")
    module_dir = os.path.join(course_content_path, module.source_path)

    if not os.path.isdir(module_dir):
        raise ValueError(f"Directorio del módulo no encontrado: {module_dir}")

    # Índice de lecciones existentes por slug para lookup O(1)
    existing_by_slug: Dict[str, Lesson] = {les.slug: les for les in module.lessons}

    # Determinar el orden máximo actual para no pisar IDs existentes
    current_max_order = max((les.order for les in module.lessons), default=0)

    added = 0
    updated = 0

    # ── Paso 1: archivos .md numerados (lecciones de teoría) ──────────────
    numbered_mds = scan_numbered_md_files(module_dir)
    theory_order = 0
    for md_file in numbered_mds:
        theory_order += 1
        slug = slugify(md_file)
        full_path = os.path.join(module_dir, md_file)
        meta = _file_meta(full_path, md_file)

        if slug in existing_by_slug:
            # Actualizar lesson existente
            les = existing_by_slug[slug]
            les.content_path = md_file
            les.title = humanize_title(md_file)
            les.order = theory_order
            les.size_bytes = meta.get("size_bytes")
            les.line_count = meta.get("line_count")
            updated += 1
        else:
            # Insertar nueva lesson
            db.add(Lesson(
                module_id=module.id,
                title=humanize_title(md_file),
                slug=slug,
                order=theory_order,
                lesson_type="theory",
                content_path=md_file,
                is_preview=False,
                estimated_minutes=15,
                **meta,
            ))
            added += 1

    # ── Paso 2: archivos de código ────────────────────────────────────────
    code_order = current_max_order if not numbered_mds else theory_order
    for code_dir in _get_code_dirs(module_dir):
        scan_path = os.path.join(module_dir, code_dir) if code_dir != "." else module_dir
        if not os.path.isdir(scan_path):
            continue
        try:
            code_files_list = sorted(os.listdir(scan_path))
        except OSError:
            continue

        for code_file in code_files_list:
            if not is_content_file(code_file):
                continue
            # Saltar .md: ya se procesaron arriba como teoría
            if code_file.endswith(".md") and code_dir not in {"src", "cpp", "python", "exercises"}:
                continue

            slug = slugify(code_file)
            content_rel_path = (
                os.path.join(code_dir, code_file) if code_dir != "." else code_file
            )
            full_path = os.path.join(module_dir, content_rel_path)
            meta = _file_meta(full_path, code_file)

            if slug in existing_by_slug:
                les = existing_by_slug[slug]
                les.content_path = content_rel_path
                les.size_bytes = meta.get("size_bytes")
                les.line_count = meta.get("line_count")
                updated += 1
            else:
                code_order += 1
                db.add(Lesson(
                    module_id=module.id,
                    title=code_file if code_file.endswith(('.c', '.cpp', '.py', '.h', '.vhd', '.ino')) else humanize_title(code_file),
                    slug=slug,
                    order=code_order,
                    lesson_type=get_lesson_type(code_file),
                    content_path=content_rel_path,
                    is_preview=False,
                    estimated_minutes=10,
                    **meta,
                ))
                added += 1

    await db.commit()
    return {
        "module_id": module.id,
        "module_slug": module.slug,
        "added": added,
        "updated": updated,
    }


async def scan_and_seed_courses(db: AsyncSession) -> Dict[str, Any]:
    """
    Escanea el filesystem y crea cursos, módulos y lecciones en la BD.
    
    Algoritmo:
    1. Para cada curso predefinido:
       a. Verificar si ya existe (por slug). Si sí, omitir.
       b. Crear el Course en la BD.
       c. Listar subdirectorios del source_path → Modules
       d. Para cada módulo, listar archivos → Lessons
    
    Retorna un resumen de lo creado.
    """
    results = {"created": [], "skipped": [], "errors": []}
    base_path = settings.CONTENT_BASE_PATH

    for course_def in PREDEFINED_COURSES:
        # Verificar si ya existe
        existing = await db.execute(
            select(Course).where(Course.slug == course_def["slug"])
        )
        if existing.scalar_one_or_none():
            results["skipped"].append(course_def["slug"])
            continue

        # Verificar que la carpeta existe
        course_path = resolve_course_content_path(course_def["source_path"], "es")
        root_path = os.path.join(base_path, course_def["source_path"])
        if not os.path.isdir(root_path):
            results["errors"].append(
                f"{course_def['slug']}: carpeta no encontrada ({root_path})"
            )
            continue

        # Crear curso
        course = Course(
            title=course_def["title"],
            slug=course_def["slug"],
            description=course_def["description"],
            short_description=course_def["short_description"],
            title_en=course_def.get("title_en"),
            description_en=course_def.get("description_en"),
            short_description_en=course_def.get("short_description_en"),
            language=course_def["language"],
            difficulty=course_def["difficulty"],
            estimated_hours=course_def.get("estimated_hours"),
            price=course_def["price"],
            price_usd=course_def.get("price_usd", 0.0),
            ls_checkout_url=course_def.get("ls_checkout_url"),
            source_path=course_def["source_path"],
            image_url=course_def.get("image_url"),
            is_published=True,
        )
        db.add(course)
        await db.flush()  # Obtener el ID sin hacer commit

        # ----------------------------------------------------------
        # Escanear módulos (subdirectorios del curso)
        # ----------------------------------------------------------
        module_order = 0
        try:
            entries = sorted(os.listdir(course_path))
        except OSError:
            results["errors"].append(f"{course_def['slug']}: error leyendo directorio")
            continue

        for entry in entries:
            entry_path = os.path.join(course_path, entry)

            # Solo directorios que parecen módulos (empiezan con número o "module"/"proyecto")
            if not os.path.isdir(entry_path):
                continue

            # Filtrar carpetas de build, .git, common, etc.
            skip_dirs = {
                "build", ".git", "__pycache__", "common", "utils",
                "assets", "libro", "book", ".venv", "node_modules",
                "docs",  # Para ESP32, los docs son módulos especiales
            }
            if entry.startswith(".") or entry in skip_dirs:
                continue

            module_order += 1
            # Detectar título en inglés desde carpeta en/
            en_module_name = _find_en_module_dir(root_path, entry)
            module = Module(
                course_id=course.id,
                title=humanize_title(entry),
                title_en=humanize_title(en_module_name) if en_module_name else None,
                slug=slugify(entry),
                order=module_order,
                source_path=entry,
            )
            db.add(module)
            await db.flush()

            # ----------------------------------------------------------
            # Escanear lecciones (archivos dentro del módulo)
            # ----------------------------------------------------------
            lesson_order = 0

            # Prioridad 1: archivos .md numerados (01_intro.md, 02_impl.md, …)
            # Si existen, se usan como lecciones individuales y se ignora README.md.
            # Prioridad 2: README.md único (comportamiento original).
            numbered_mds = scan_numbered_md_files(entry_path)
            if numbered_mds:
                for md_file in numbered_mds:
                    lesson_order += 1
                    db.add(_make_lesson(entry_path,
                        module_id=module.id,
                        title=humanize_title(md_file),
                        title_en=_find_en_lesson_title(root_path, en_module_name, md_file),
                        slug=slugify(md_file),
                        order=lesson_order,
                        lesson_type="theory",
                        content_path=md_file,
                        is_preview=(module_order == 1 and lesson_order == 1),
                        estimated_minutes=15,
                    ))
            else:
                readme_path = os.path.join(entry_path, "README.md")
                if os.path.isfile(readme_path):
                    lesson_order += 1
                    db.add(_make_lesson(entry_path,
                        module_id=module.id,
                        title=f"{humanize_title(entry)} - Teoría",
                        title_en=f"{humanize_title(en_module_name)} - Theory" if en_module_name else None,
                        slug="teoria",
                        order=lesson_order,
                        lesson_type="theory",
                        content_path="README.md",
                        is_preview=(module_order == 1 and lesson_order == 1),
                        estimated_minutes=15,
                    ))

            # Luego buscar archivos de código. _get_code_dirs descubre
            # dinámicamente subdirs extra (ej: sketches Arduino minimo/).
            for code_dir in _get_code_dirs(entry_path):
                scan_path = os.path.join(entry_path, code_dir) if code_dir != "." else entry_path
                if not os.path.isdir(scan_path):
                    continue

                try:
                    code_files = sorted(os.listdir(scan_path))
                except OSError:
                    continue

                for code_file in code_files:
                    if not is_content_file(code_file):
                        continue
                    # Saltar .md en raíz y en subdirs descubiertos: ya fueron
                    # procesados como teoría, o no son lecciones intencionales.
                    if code_file.endswith(".md") and code_dir not in {"src", "cpp", "python", "exercises"}:
                        continue

                    lesson_order += 1
                    content_rel_path = (
                        os.path.join(code_dir, code_file)
                        if code_dir != "."
                        else code_file
                    )

                    lesson = _make_lesson(entry_path,
                        module_id=module.id,
                        title=humanize_title(code_file) if not code_file.endswith(('.c', '.cpp', '.py', '.h', '.vhd', '.ino')) else code_file,
                        title_en=_find_en_lesson_title(root_path, en_module_name, code_file),
                        slug=slugify(code_file),
                        order=lesson_order,
                        lesson_type=get_lesson_type(code_file),
                        content_path=content_rel_path,
                        is_preview=False,
                        estimated_minutes=10,
                    )
                    db.add(lesson)

        results["created"].append({
            "slug": course_def["slug"],
            "modules": module_order,
        })

    await db.commit()
    return results


# ==============================================================
# Funciones para el panel admin (crear curso individual)
# ==============================================================

def preview_course_folder(source_path: str) -> dict:
    """
    Analiza la estructura de una carpeta y devuelve un preview
    de los módulos y lecciones que se crearían, sin escribir en BD.

    Args:
        source_path: Nombre relativo a CONTENT_BASE_PATH (ej: "ProjectDsp")
    Returns:
        {"source_path": ..., "module_count": N, "modules": [...]}
    Raises:
        ValueError: Si la carpeta no existe.
    """
    base_path = settings.CONTENT_BASE_PATH
    course_path = resolve_course_content_path(source_path, "es")

    if not os.path.isdir(course_path):
        raise ValueError(f"Carpeta no encontrada: {os.path.join(base_path, source_path)}")

    skip_dirs = {
        "build", ".git", "__pycache__", "common", "utils",
        "assets", "libro", "book", ".venv", "node_modules", "docs",
    }

    try:
        entries = sorted(os.listdir(course_path))
    except OSError:
        raise ValueError(f"Error leyendo directorio: {course_path}")

    modules_preview = []
    for entry in entries:
        entry_path = os.path.join(course_path, entry)
        if not os.path.isdir(entry_path):
            continue
        if entry.startswith(".") or entry in skip_dirs:
            continue

        lesson_count = 0
        numbered_mds = scan_numbered_md_files(entry_path)
        if numbered_mds:
            lesson_count += len(numbered_mds)
        elif os.path.isfile(os.path.join(entry_path, "README.md")):
            lesson_count += 1

        seen_files: set = set()
        for code_dir in _get_code_dirs(entry_path):
            scan_path = (
                os.path.join(entry_path, code_dir)
                if code_dir != "."
                else entry_path
            )
            if not os.path.isdir(scan_path):
                continue
            try:
                for code_file in sorted(os.listdir(scan_path)):
                    if code_file.endswith(".md") and code_dir not in {"src", "cpp", "python", "exercises"}:
                        continue
                    if is_content_file(code_file) and code_file not in seen_files:
                        lesson_count += 1
                        seen_files.add(code_file)
            except OSError:
                continue

        modules_preview.append({
            "name": entry,
            "title": humanize_title(entry),
            "lesson_count": lesson_count,
        })

    return {
        "source_path": source_path,
        "module_count": len(modules_preview),
        "modules": modules_preview,
    }


async def _scan_modules_for_course(
    course: Course,
    course_path: str,
    db: AsyncSession,
) -> int:
    """
    Popula módulos y lecciones para un Course ya creado en BD.
    Lógica idéntica a scan_and_seed_courses pero para un solo curso.

    Returns:
        Número de módulos creados.
    """
    skip_dirs = {
        "build", ".git", "__pycache__", "common", "utils",
        "assets", "libro", "book", ".venv", "node_modules", "docs",
    }

    module_order = 0
    try:
        entries = sorted(os.listdir(course_path))
    except OSError:
        return 0

    for entry in entries:
        entry_path = os.path.join(course_path, entry)
        if not os.path.isdir(entry_path):
            continue
        if entry.startswith(".") or entry in skip_dirs:
            continue

        module_order += 1
        module = Module(
            course_id=course.id,
            title=humanize_title(entry),
            slug=slugify(entry),
            order=module_order,
            source_path=entry,
        )
        db.add(module)
        await db.flush()

        lesson_order = 0
        numbered_mds = scan_numbered_md_files(entry_path)
        if numbered_mds:
            for md_file in numbered_mds:
                lesson_order += 1
                db.add(_make_lesson(entry_path,
                    module_id=module.id,
                    title=humanize_title(md_file),
                    slug=slugify(md_file),
                    order=lesson_order,
                    lesson_type="theory",
                    content_path=md_file,
                    is_preview=(module_order == 1 and lesson_order == 1),
                    estimated_minutes=15,
                ))
        else:
            readme_path = os.path.join(entry_path, "README.md")
            if os.path.isfile(readme_path):
                lesson_order += 1
                db.add(_make_lesson(entry_path,
                    module_id=module.id,
                    title=f"{humanize_title(entry)} - Teoría",
                    slug="teoria",
                    order=lesson_order,
                    lesson_type="theory",
                    content_path="README.md",
                    is_preview=(module_order == 1 and lesson_order == 1),
                    estimated_minutes=15,
                ))

        for code_dir in _get_code_dirs(entry_path):
            scan_path = (
                os.path.join(entry_path, code_dir)
                if code_dir != "."
                else entry_path
            )
            if not os.path.isdir(scan_path):
                continue
            try:
                code_files = sorted(os.listdir(scan_path))
            except OSError:
                continue
            for code_file in code_files:
                if not is_content_file(code_file):
                    continue
                # Saltar .md en raíz y en subdirs descubiertos: ya fueron
                # procesados como teoría, o no son lecciones intencionales.
                if code_file.endswith(".md") and code_dir not in {"src", "cpp", "python", "exercises"}:
                    continue
                lesson_order += 1
                content_rel_path = (
                    os.path.join(code_dir, code_file)
                    if code_dir != "."
                    else code_file
                )
                db.add(_make_lesson(entry_path,
                    module_id=module.id,
                    title=(
                        humanize_title(code_file)
                        if not code_file.endswith(('.c', '.cpp', '.py', '.h', '.vhd', '.ino'))
                        else code_file
                    ),
                    slug=slugify(code_file),
                    order=lesson_order,
                    lesson_type=get_lesson_type(code_file),
                    content_path=content_rel_path,
                    is_preview=False,
                    estimated_minutes=10,
                ))

    return module_order


async def create_course_with_scan(course_def: dict, db: AsyncSession) -> dict:
    """
    Crea un curso individual en la BD y escanea su carpeta
    para poblar módulos y lecciones automáticamente.

    Uso: llamar desde el panel admin al crear un nuevo curso.

    Args:
        course_def: Dict con campos del curso. Requiere: title, slug,
                    description, short_description, source_path, price.
                    Opcionales: language, difficulty, estimated_hours,
                    image_url, is_published.
        db: Sesión async de SQLAlchemy.
    Returns:
        {"id": int, "slug": str, "module_count": int}
    Raises:
        ValueError: Si la carpeta no existe o el slug ya está en uso.
    """
    base_path = settings.CONTENT_BASE_PATH
    course_path = resolve_course_content_path(course_def["source_path"], "es")
    root_path = os.path.join(base_path, course_def["source_path"])

    if not os.path.isdir(root_path):
        raise ValueError(f"Carpeta no encontrada: {root_path}")

    existing = await db.execute(
        select(Course).where(Course.slug == course_def["slug"])
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Ya existe un curso con slug '{course_def['slug']}'")

    course = Course(
        title=course_def["title"],
        slug=course_def["slug"],
        description=course_def.get("description", ""),
        short_description=course_def.get("short_description", ""),
        title_en=course_def.get("title_en"),
        description_en=course_def.get("description_en"),
        short_description_en=course_def.get("short_description_en"),
        language=course_def.get("language", "C/C++"),
        difficulty=course_def.get("difficulty", "intermediate"),
        estimated_hours=course_def.get("estimated_hours"),
        price=course_def.get("price", 0.0),
        price_usd=course_def.get("price_usd", 0.0),
        source_path=course_def["source_path"],
        image_url=course_def.get("image_url"),
        is_published=course_def.get("is_published", True),
    )
    db.add(course)
    await db.flush()

    module_count = await _scan_modules_for_course(course, course_path, db)
    await db.commit()

    return {"id": course.id, "slug": course.slug, "module_count": module_count}
