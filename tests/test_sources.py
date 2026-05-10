from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rawtowise.compile import _read_compilable_sources
from rawtowise.ingest import ingest_source
from rawtowise.sources import (
    ensure_wiki_scaffold,
    load_manifest,
    rel_path,
    sha256_file,
    upsert_source,
)


class SourceManifestTests(unittest.TestCase):
    def test_scaffold_creates_schema_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)

            ensure_wiki_scaffold(project, "Test KB")

            self.assertTrue((project / "wiki" / "AGENTS.md").exists())
            self.assertTrue((project / "wiki" / "log.md").exists())
            self.assertIn("Test KB", (project / "wiki" / "AGENTS.md").read_text())

    def test_ingest_markdown_updates_manifest_and_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "note.md"
            source.write_text("# Attention\n\nTransformers use attention.\n", encoding="utf-8")

            saved = ingest_source(str(source), project)

            manifest = load_manifest(project)
            self.assertEqual(len(saved), 1)
            self.assertEqual(len(manifest["sources"]), 1)
            record = next(iter(manifest["sources"].values()))
            self.assertEqual(record["status"], "ready")
            self.assertEqual(record["parser"], "native")
            self.assertTrue((project / record["raw_path"]).exists())
            self.assertTrue((project / "wiki" / "log.md").exists())

            docs = _read_compilable_sources(project)
            self.assertEqual(set(docs), {record["id"]})
            self.assertIn("Transformers use attention", next(iter(docs.values())).content)

    def test_loader_prefers_processed_markdown_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            raw = project / "raw" / "papers" / "paper.pdf"
            processed = project / ".rtw" / "processed" / "sources" / "paper-123.md"
            raw.parent.mkdir(parents=True)
            processed.parent.mkdir(parents=True)
            raw.write_bytes(b"%PDF placeholder")
            processed.write_text("# Paper\n\nConverted text.\n", encoding="utf-8")

            upsert_source(project, {
                "id": "paper-123",
                "title": "Paper",
                "kind": "file",
                "source": "paper.pdf",
                "raw_path": rel_path(project, raw),
                "processed_path": rel_path(project, processed),
                "sha256": sha256_file(raw),
                "processed_sha256": sha256_file(processed),
                "parser": "markitdown",
                "status": "ready",
            })

            docs = _read_compilable_sources(project)

            self.assertEqual(set(docs), {"paper-123"})
            self.assertEqual(docs["paper-123"].path, ".rtw/processed/sources/paper-123.md")
            self.assertIn("Converted text", docs["paper-123"].content)


if __name__ == "__main__":
    unittest.main()
