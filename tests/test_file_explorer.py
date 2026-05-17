"""
============================================================
test_file_explorer.py - Tests para el Code Explorer feature
============================================================

Valida:
- LessonMeta con relative_path para tree building
- Lógica de árbol de archivos (buildFileTree equivalente en Python)
- Consistencia del contrato frontend ↔ backend
- resolveCodeLanguage mapping
- formatFileSize conversiones
"""

import pytest
from app.schemas.course import LessonMeta


# ----------------------------------------------------------
# Helpers: reimplementación Python de fileTreeUtils.js
# para validar que el contrato de datos funciona
# ----------------------------------------------------------
EXT_LANG_MAP = {
    '.c': 'c', '.h': 'c',
    '.cpp': 'cpp', '.hpp': 'cpp', '.cc': 'cpp',
    '.ino': 'cpp',
    '.py': 'python',
    '.vhd': 'vhdl', '.vhdl': 'vhdl',
    '.v': 'verilog', '.sv': 'systemverilog',
    '.sh': 'bash',
    '.mk': 'makefile', '.cmake': 'cmake',
    '.rs': 'rust',
    '.js': 'javascript', '.ts': 'typescript',
    '.json': 'json',
    '.yaml': 'yaml', '.yml': 'yaml',
    '.toml': 'toml',
    '.md': 'markdown',
}


def resolve_code_language(file: dict) -> str:
    """Replica la lógica de resolveCodeLanguage del frontend."""
    if not file:
        return "text"
    if file.get("language"):
        return file["language"]
    name = file.get("filename") or file.get("relative_path") or ""
    dot_idx = name.rfind(".")
    if dot_idx >= 0:
        ext = name[dot_idx:].lower()
        if ext in EXT_LANG_MAP:
            return EXT_LANG_MAP[ext]
    return "text"


def build_file_tree(files: list) -> list:
    """Replica la lógica de buildFileTree del frontend."""
    if not files:
        return []

    root = {}
    for f in files:
        path = f.get("relative_path") or f.get("filename") or ""
        parts = [p for p in path.split("/") if p]
        current = root
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            if is_last:
                current[part] = {"__file": f}
            else:
                if part not in current or "__file" in current.get(part, {}):
                    current.setdefault(part, {})
                current = current[part]

    def map_to_nodes(obj):
        folders, file_nodes = [], []
        for name, value in obj.items():
            if name == "__file":
                continue
            if "__file" in value:
                file_nodes.append({"name": name, "type": "file", "file": value["__file"]})
            else:
                folders.append({"name": name, "type": "folder", "children": map_to_nodes(value)})
        folders.sort(key=lambda x: x["name"])
        file_nodes.sort(key=lambda x: x["name"])
        return folders + file_nodes

    return map_to_nodes(root)


def format_file_size(b) -> str | None:
    """Replica la lógica de formatFileSize del frontend."""
    if b is None:
        return None
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b / (1024 * 1024):.1f} MB"


# ----------------------------------------------------------
# Fixtures
# ----------------------------------------------------------
def _meta(slug, filename, rel_path, lang="c", size=1024, lines=42):
    return LessonMeta(
        id=1, title=filename, slug=slug, lesson_type="code",
        filename=filename, relative_path=rel_path,
        size_bytes=size, line_count=lines, language=lang,
    )


# ----------------------------------------------------------
# buildFileTree
# ----------------------------------------------------------
class TestBuildFileTree:
    """Árbol de archivos desde relative_path plano."""

    def test_single_root_file(self):
        files = [{"relative_path": "Makefile", "filename": "Makefile"}]
        tree = build_file_tree(files)
        assert len(tree) == 1
        assert tree[0]["name"] == "Makefile"
        assert tree[0]["type"] == "file"

    def test_single_nested_file(self):
        files = [{"relative_path": "src/main.c", "filename": "main.c"}]
        tree = build_file_tree(files)
        assert len(tree) == 1
        assert tree[0]["name"] == "src"
        assert tree[0]["type"] == "folder"
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["name"] == "main.c"

    def test_multiple_files_same_folder(self):
        files = [
            {"relative_path": "src/main.c", "filename": "main.c"},
            {"relative_path": "src/util.c", "filename": "util.c"},
            {"relative_path": "src/util.h", "filename": "util.h"},
        ]
        tree = build_file_tree(files)
        assert len(tree) == 1  # solo carpeta src
        children = tree[0]["children"]
        assert len(children) == 3
        names = [c["name"] for c in children]
        assert names == ["main.c", "util.c", "util.h"]  # ordenados

    def test_deep_nesting(self):
        files = [{"relative_path": "a/b/c/deep.c", "filename": "deep.c"}]
        tree = build_file_tree(files)
        assert tree[0]["name"] == "a"
        assert tree[0]["children"][0]["name"] == "b"
        assert tree[0]["children"][0]["children"][0]["name"] == "c"
        assert tree[0]["children"][0]["children"][0]["children"][0]["name"] == "deep.c"

    def test_folders_before_files(self):
        """Carpetas primero, archivos después (ambos alfabéticos)."""
        files = [
            {"relative_path": "z_file.c", "filename": "z_file.c"},
            {"relative_path": "a_dir/nested.c", "filename": "nested.c"},
            {"relative_path": "m_file.c", "filename": "m_file.c"},
            {"relative_path": "b_dir/other.c", "filename": "other.c"},
        ]
        tree = build_file_tree(files)
        # Carpetas primero
        assert tree[0]["type"] == "folder"
        assert tree[0]["name"] == "a_dir"
        assert tree[1]["type"] == "folder"
        assert tree[1]["name"] == "b_dir"
        # Archivos después
        assert tree[2]["type"] == "file"
        assert tree[2]["name"] == "m_file.c"
        assert tree[3]["type"] == "file"
        assert tree[3]["name"] == "z_file.c"

    def test_empty_list(self):
        assert build_file_tree([]) == []

    def test_none_input(self):
        assert build_file_tree(None) == []

    def test_real_blockchain_structure(self):
        """Simula estructura real: 01_hashing con src/, include/, Makefile."""
        files = [
            {"relative_path": "src/sha256.c", "filename": "sha256.c"},
            {"relative_path": "src/main.c", "filename": "main.c"},
            {"relative_path": "include/sha256.h", "filename": "sha256.h"},
            {"relative_path": "Makefile", "filename": "Makefile"},
        ]
        tree = build_file_tree(files)
        # Dos carpetas + un archivo raíz
        assert tree[0]["type"] == "folder"  # include
        assert tree[1]["type"] == "folder"  # src
        assert tree[2]["type"] == "file"    # Makefile

        # src contiene main.c, sha256.c
        src = tree[1]
        assert src["name"] == "src"
        assert [c["name"] for c in src["children"]] == ["main.c", "sha256.c"]

    def test_real_arduino_structure(self):
        """Simula estructura Arduino: subdir/file.ino"""
        files = [
            {"relative_path": "hello_serial/hello_serial.ino", "filename": "hello_serial.ino"},
        ]
        tree = build_file_tree(files)
        assert tree[0]["name"] == "hello_serial"
        assert tree[0]["type"] == "folder"
        assert tree[0]["children"][0]["name"] == "hello_serial.ino"

    def test_preserves_file_reference(self):
        """El nodo file preserva la referencia original del objeto."""
        orig = {"relative_path": "src/main.c", "filename": "main.c", "slug": "main-c"}
        tree = build_file_tree([orig])
        file_node = tree[0]["children"][0]
        assert file_node["file"]["slug"] == "main-c"
        assert file_node["file"] is orig


# ----------------------------------------------------------
# resolveCodeLanguage
# ----------------------------------------------------------
class TestResolveCodeLanguage:
    """Determina lenguaje para syntax highlighting."""

    def test_backend_language_has_priority(self):
        assert resolve_code_language({"language": "rust", "filename": "main.c"}) == "rust"

    def test_extension_fallback(self):
        assert resolve_code_language({"filename": "main.c"}) == "c"
        assert resolve_code_language({"filename": "app.py"}) == "python"
        assert resolve_code_language({"filename": "blink.ino"}) == "cpp"
        assert resolve_code_language({"filename": "top.vhd"}) == "vhdl"

    def test_extension_from_relative_path(self):
        assert resolve_code_language({"relative_path": "src/main.rs"}) == "rust"

    def test_unknown_extension_returns_text(self):
        assert resolve_code_language({"filename": "data.xyz"}) == "text"

    def test_no_extension_returns_text(self):
        assert resolve_code_language({"filename": "Makefile"}) == "text"

    def test_empty_input(self):
        assert resolve_code_language({}) == "text"
        assert resolve_code_language(None) == "text"

    def test_yaml_variants(self):
        assert resolve_code_language({"filename": "config.yaml"}) == "yaml"
        assert resolve_code_language({"filename": "docker-compose.yml"}) == "yaml"

    def test_case_insensitive_extension(self):
        assert resolve_code_language({"filename": "MODULE.CPP"}) == "cpp"


# ----------------------------------------------------------
# formatFileSize
# ----------------------------------------------------------
class TestFormatFileSize:
    """Formatea bytes a formato legible."""

    def test_bytes(self):
        assert format_file_size(0) == "0 B"
        assert format_file_size(512) == "512 B"
        assert format_file_size(1023) == "1023 B"

    def test_kilobytes(self):
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(2048) == "2.0 KB"
        assert format_file_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_file_size(1024 * 1024) == "1.0 MB"
        assert format_file_size(5 * 1024 * 1024) == "5.0 MB"

    def test_none_returns_none(self):
        assert format_file_size(None) is None


# ----------------------------------------------------------
# Contrato: LessonMeta como input para buildFileTree
# ----------------------------------------------------------
class TestMetaToTreeContract:
    """Valida que LessonMeta serializado es input válido para buildFileTree."""

    def test_meta_dict_builds_valid_tree(self):
        """model_dump() produce dict compatible con buildFileTree."""
        metas = [
            _meta("sha256-c", "sha256.c", "src/sha256.c"),
            _meta("main-c", "main.c", "src/main.c"),
            _meta("sha256-h", "sha256.h", "include/sha256.h"),
            _meta("makefile", "Makefile", "Makefile", lang="makefile"),
        ]
        dicts = [m.model_dump() for m in metas]
        tree = build_file_tree(dicts)

        assert len(tree) == 3  # include/, src/, Makefile
        folder_names = [n["name"] for n in tree if n["type"] == "folder"]
        assert "src" in folder_names
        assert "include" in folder_names

    def test_single_ino_file_in_subdir(self):
        meta = _meta("hello-ino", "hello.ino", "hello_serial/hello.ino", lang="cpp")
        tree = build_file_tree([meta.model_dump()])
        assert tree[0]["type"] == "folder"
        assert tree[0]["children"][0]["file"]["slug"] == "hello-ino"
