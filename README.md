<p align="center">
  <h1 align="center">RawToWise</h1>
  <p align="center">
    <strong>LLM Knowledge Compiler</strong> — drop raw documents, get a structured markdown wiki.
  </p>
  <p align="center">
    <a href="#install">Install</a> &middot;
    <a href="#quick-start">Quick Start</a> &middot;
    <a href="#how-it-works">How It Works</a> &middot;
    <a href="CONTRIBUTING.md">Contributing</a>
  </p>
</p>

---

https://github.com/user-attachments/assets/2dd7bb29-8f4f-44ff-a5c4-f303b055e7ce

```
raw/ (papers, articles, URLs)
  → rtw compile → wiki/ (structured .md with backlinks)
                    → rtw query → answers accumulate in wiki
                    → rtw lint  → detect contradictions, fill gaps
```

Inspired by [Andrej Karpathy's LLM knowledge base workflow](https://x.com/karpathy/status/2039805659525644595). Turn his "hacky collection of scripts" into a real tool.

## Why RawToWise?

| Problem | RawToWise |
|---------|-----------|
| RAG requires vector DB infra | **No vector DB** — LLM navigates via index + backlinks |
| Chat answers disappear | **Exploration = accumulation** — every query enriches the wiki |
| PKM requires manual organizing | **Drop and forget** — put files in `raw/`, LLM handles the rest |
| Vendor lock-in (NotebookLM, etc.) | **Plain markdown** — works in Obsidian, VSCode, or any editor |

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/vericontext/rawtowise/main/install.sh | bash
```

<details>
<summary>Other install methods</summary>

```bash
# Via pipx
pipx install git+https://github.com/vericontext/rawtowise.git

# Via uv
uv tool install git+https://github.com/vericontext/rawtowise.git

# From source
git clone https://github.com/vericontext/rawtowise.git && cd rawtowise && pip install -e .
```

</details>

RawToWise can run through your logged-in **Codex** or **Claude Code** CLI session, so a separate API key is not required for local use. Direct Anthropic API usage is still supported with `ANTHROPIC_API_KEY`.

## Quick Start

```bash
# 1. Initialize a project
rtw init --name "AI Research"

# 2. Ingest sources
rtw ingest https://example.com/article
rtw ingest "https://en.wikipedia.org/wiki/Transformer_(deep_learning)"
rtw ingest paper.pdf
rtw ingest ./my-articles/

# 3. Compile into a wiki
rtw compile

# 4. Ask questions (answers stream in real-time)
rtw query "What are the key debates in this field?"

# 5. Health check
rtw lint
```

## How It Works

**Ingest** — Fetch URLs (via [Jina Reader](https://jina.ai/reader/)), copy local files into `raw/`, and convert supported document formats to Markdown with [MarkItDown](https://github.com/microsoft/markitdown). Raw sources stay intact; processed Markdown and source metadata live under `.rtw/`.

**Compile** — LLM extracts key concepts from all compilable sources, generates interlinked wiki articles with `[[backlinks]]` and `[source: source_id:Lx-Ly]` citations, and builds an index. Articles are generated in parallel for speed. Incremental compiles use source hashes to skip unchanged inputs.

**Query** — LLM reads the wiki index, finds relevant articles, and synthesizes an answer. Answers stream to the terminal and are saved to `output/` for future reference.

**Lint** — LLM audits the wiki for contradictions, coverage gaps, stale information, and suggested explorations. RawToWise also checks dangling wikilinks, uncited concept pages, orphan pages, and stale source hashes.

## Commands

| Command | Description |
|---------|-------------|
| `rtw init` | Initialize a new project (creates dirs + config, detects LLM backend) |
| `rtw ingest <source>` | Ingest URL, file, or directory into `raw/` |
| `rtw compile` | Compile sources into wiki (incremental by default) |
| `rtw compile --full` | Full recompile from scratch |
| `rtw compile --dry-run` | Estimate token usage and cost |
| `rtw query "question"` | Ask the wiki (streamed output) |
| `rtw query "..." --format table` | Output as markdown table |
| `rtw query "..." --deep` | Deep research mode (longer output) |
| `rtw lint` | Run wiki health check |
| `rtw stats` | Show wiki statistics |

## Project Structure

```
my-research/
├── rtw.yaml              # Configuration
├── .env                  # Optional API key overrides (gitignored)
├── raw/                  # Raw sources — you add files here
│   ├── articles/         #   Web articles (auto-sorted)
│   ├── papers/           #   PDFs (auto-sorted)
│   ├── documents/        #   Office/ePub docs
│   └── data/             #   CSV/JSON/XML/Excel files
├── wiki/                 # LLM-generated wiki — don't edit manually
│   ├── AGENTS.md         #   Wiki schema + maintenance rules
│   ├── _index.md         #   Master index
│   ├── _sources.md       #   Source catalog
│   ├── log.md            #   Append-only operation log
│   └── concepts/         #   Concept articles with [[backlinks]]
├── output/               # Query results
│   └── queries/          #   Saved answers
└── .rtw/                 # Internal state (manifest, processed markdown, debug logs)
    ├── sources.json      #   Source manifest with hashes/provenance
    └── processed/        #   Markdown converted from PDFs/Office/etc.
```

## Configuration

`rtw.yaml` (auto-generated by `rtw init`):

```yaml
version: 1
name: "My Research"

llm:
  provider: auto                   # auto, anthropic, codex, or claude-code
  compile: claude-sonnet-4-6      # Fast model for compilation
  query: claude-sonnet-4-6        # Query answering
  lint: claude-haiku-4-5-20251001 # Economical model for health checks
  codex_model: ""                 # Optional Codex model override
  claude_code_model: ""           # Optional Claude Code model override
  timeout_seconds: 600

compile:
  strategy: incremental
  max_concepts: 200
  language: en                    # Wiki language
```

`llm.provider: auto` resolves in this order:

1. Active Codex session + `codex` CLI
2. Active Claude Code session + `claude` CLI
3. `ANTHROPIC_API_KEY`
4. Installed Claude Code CLI
5. Installed Codex CLI

You can force a backend per run:

```bash
RAWTOWISE_LLM_PROVIDER=codex rtw compile
RAWTOWISE_LLM_PROVIDER=claude-code rtw query "..."
RAWTOWISE_LLM_PROVIDER=anthropic rtw lint
```

## Agent-Assisted Development

This repository is set up for both Codex and Claude Code:

- `AGENTS.md` — shared repository instructions for Codex, Claude Code, and other agents
- `CLAUDE.md` — Claude Code entry point that delegates to `AGENTS.md`
- `.codex/config.toml` — project-scoped Codex defaults and hook enablement
- `.codex/hooks.json` + `.codex/hooks/` — Codex hooks for version sync, patch auto-bump on `git commit`, and destructive command guards
- `.claude/` — Claude Code hooks for the same version sync / auto-bump workflow

Keep personal choices such as model, auth method, sandbox, approval policy, telemetry, and MCP servers in your user-level Codex or Claude Code config. Project hooks may require starting a new trusted Codex session before they load.

## Viewing the Wiki

The compiled wiki is plain markdown with `[[wiki-links]]`. Best viewed with:

- **[Obsidian](https://obsidian.md/)** — open `wiki/` as a vault. Graph view shows concept connections.
- **VSCode + [Foam](https://marketplace.visualstudio.com/items?itemName=foam.foam-vscode)** — `[[backlink]]` support with graph visualization.
- **Any markdown viewer** — files are standard `.md`, readable anywhere.

## Cost

RawToWise can use your logged-in Codex or Claude Code CLI session. Those backends follow your CLI account's subscription, rate limit, or usage policy. If you set `llm.provider: anthropic` or `ANTHROPIC_API_KEY`, RawToWise calls the Anthropic API directly and API billing applies.

| Operation | Anthropic API estimate |
|-----------|----------|
| Ingest URL/file | No LLM API call |
| Compile 5 sources | ~$1-2 |
| Single query | ~$0.05-0.15 |
| Lint | ~$0.50 |

Use `rtw compile --dry-run` to estimate compile input size before compiling. Cost estimates are only meaningful for direct API backends.

## Roadmap

See [open issues labeled `roadmap`](https://github.com/vericontext/rawtowise/labels/roadmap) for planned features, including:

- YouTube transcript support
- Review/approval mode for generated wiki edits
- Hybrid local search (BM25/vector/rerank)
- Ollama/local model support
- Obsidian plugin
- MCP server for AI agents

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/vericontext/rawtowise/main/uninstall.sh | bash
```

## License

[MIT](LICENSE)
