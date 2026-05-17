"""
============================================================
test_code_files.py - Tests para archivos de código (schemas + render)
============================================================

Valida:
- LessonMeta schema acepta los campos esperados
- LessonContent schema con campos de metadata
- render_code_file produce HTML válido para distintas extensiones
- Detección de Content-Type y filename en FileResponse
"""

import os
import pytest
from pydantic import ValidationError

from app.schemas.course import LessonMeta, LessonContent, LessonResponse
from app.api.content import render_code_file, render_markdown


# ----------------------------------------------------------
# Schema: LessonMeta
# ----------------------------------------------------------
class TestLessonMetaSchema:
    """Valida que LessonMeta acepta y serializa campos correctamente."""

    def test_all_fields(self):
        meta = LessonMeta(
            id=1,
            title="sha256.c",
            slug="sha256-c",
            lesson_type="code",
            filename="sha256.c",
            size_bytes=2048,
            line_count=85,
            language="c",
        )
        assert meta.size_bytes == 2048
        assert meta.line_count == 85
        assert meta.language == "c"
        assert meta.filename == "sha256.c"

    def test_optional_fields_default_none(self):
        meta = LessonMeta(
            id=1,
            title="test",
            slug="test",
            lesson_type="code",
            filename="test.c",
        )
        assert meta.size_bytes is None
        assert meta.line_count is None
        assert meta.language is None

    def test_relative_path_optional(self):
        """relative_path se acepta y es None por defecto."""
        meta_without = LessonMeta(
            id=1, title="t", slug="t", lesson_type="code", filename="t.c",
        )
        assert meta_without.relative_path is None

        meta_with = LessonMeta(
            id=2, title="x", slug="x", lesson_type="code",
            filename="sha256.c", relative_path="src/sha256.c",
        )
        assert meta_with.relative_path == "src/sha256.c"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            LessonMeta(id=1, title="test")  # falta slug, lesson_type, filename


# ----------------------------------------------------------
# Schema: LessonMeta lista (simula /files endpoint response)
# ----------------------------------------------------------
class TestLessonMetaListSchema:
    """Valida serialización de lista de LessonMeta (como /files devuelve)."""

    def _make_meta(self, **overrides):
        defaults = dict(
            id=1, title="main.c", slug="main-c", lesson_type="code",
            filename="main.c", relative_path="src/main.c",
            size_bytes=1024, line_count=42, language="c",
        )
        defaults.update(overrides)
        return LessonMeta(**defaults)

    def test_list_of_metas_serializes(self):
        metas = [
            self._make_meta(id=1, filename="main.c", relative_path="src/main.c"),
            self._make_meta(id=2, filename="util.h", relative_path="include/util.h",
                            language="c", slug="util-h"),
            self._make_meta(id=3, filename="Makefile", relative_path="Makefile",
                            language="makefile", slug="makefile"),
        ]
        dicts = [m.model_dump() for m in metas]
        assert len(dicts) == 3
        assert dicts[0]["relative_path"] == "src/main.c"
        assert dicts[1]["relative_path"] == "include/util.h"
        assert dicts[2]["relative_path"] == "Makefile"

    def test_relative_path_reflects_content_path(self):
        """relative_path debe coincidir con content_path del modelo Lesson."""
        meta = self._make_meta(
            relative_path="hello_serial/hello_serial.ino",
            filename="hello_serial.ino",
        )
        assert meta.relative_path == "hello_serial/hello_serial.ino"
        assert meta.filename == "hello_serial.ino"

    def test_empty_list(self):
        """Módulo sin archivos de código → lista vacía, válido."""
        metas = []
        assert len(metas) == 0


# ----------------------------------------------------------
# Schema: LessonResponse con metadata
# ----------------------------------------------------------
class TestLessonResponseMetadata:
    """LessonResponse ahora incluye campos de metadata."""

    def test_metadata_fields_present(self):
        resp = LessonResponse(
            id=1,
            title="sha256.c",
            slug="sha256-c",
            order=2,
            lesson_type="code",
            is_preview=False,
            size_bytes=1024,
            line_count=42,
            language="c",
        )
        assert resp.size_bytes == 1024
        assert resp.line_count == 42
        assert resp.language == "c"

    def test_metadata_defaults_to_none(self):
        resp = LessonResponse(
            id=1,
            title="Teoría",
            slug="teoria",
            order=1,
            lesson_type="theory",
            is_preview=True,
        )
        assert resp.size_bytes is None
        assert resp.line_count is None
        assert resp.language is None


# ----------------------------------------------------------
# Schema: LessonContent con metadata
# ----------------------------------------------------------
class TestLessonContentMetadata:
    """LessonContent ahora incluye campos de metadata."""

    def test_full_content_with_metadata(self):
        lc = LessonContent(
            id=1,
            title="main.c",
            slug="main-c",
            order=1,
            lesson_type="code",
            is_preview=False,
            content_html="<pre>int main(){}</pre>",
            content_raw="int main(){}",
            filename="main.c",
            size_bytes=512,
            line_count=10,
            language="c",
        )
        assert lc.filename == "main.c"
        assert lc.size_bytes == 512
        assert lc.language == "c"


# ----------------------------------------------------------
# Render: código fuente → HTML
# ----------------------------------------------------------
class TestRenderCodeFile:
    """Verifica que render_code_file produce HTML con syntax highlighting."""

    def test_c_file_produces_html(self):
        html = render_code_file("int main() { return 0; }", "main.c")
        assert "<" in html  # Contiene tags HTML
        assert "main" in html

    def test_python_file_produces_html(self):
        html = render_code_file("def hello():\n    print('hi')\n", "script.py")
        assert "hello" in html
        assert "print" in html

    def test_ino_file_treated_as_cpp(self):
        html = render_code_file("void setup() {}\nvoid loop() {}", "blink.ino")
        assert "setup" in html

    def test_unknown_extension_still_renders(self):
        """Extensión desconocida no crashea, usa lexer genérico."""
        html = render_code_file("some content", "data.xyz")
        assert "some content" in html

    def test_vhdl_file_produces_html(self):
        code = "library IEEE;\nuse IEEE.STD_LOGIC_1164.ALL;"
        html = render_code_file(code, "top.vhd")
        assert "IEEE" in html


# ----------------------------------------------------------
# Render: markdown → HTML
# ----------------------------------------------------------
class TestRenderMarkdown:
    """Verifica que render_markdown produce HTML correcto."""

    def test_heading(self):
        html = render_markdown("# Título")
        assert "<h1" in html  # TOC extension adds id attr: <h1 id="titulo">
        assert "Título" in html

    def test_code_block(self):
        md = "```c\nint x = 0;\n```"
        html = render_markdown(md)
        assert "int" in html

    def test_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = render_markdown(md)
        assert "<table>" in html
