# RawToWise

LLM Knowledge Compiler — compiles raw documents into a structured markdown wiki.

```
raw/ (papers, articles, repos) → LLM "compile" → wiki/ (structured .md files)
                                                    ↓
                                  Q&A → answers accumulate in wiki → knowledge grows
                                                    ↓
                                  Lint → detect contradictions, fill gaps, suggest links
```

Inspired by [Andrej Karpathy's LLM knowledge base workflow](https://x.com/karpathy).

## Why

- **No vector DB needed** — LLM navigates via index files + backlinks
- **Exploration = accumulation** — every query enriches the wiki
- **Drop and forget** — put files in raw/, LLM handles the rest
- **Editor-agnostic** — plain .md files work in Obsidian, VSCode, or any editor

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/vericontext/rawtowise/main/install.sh | bash
```

Or manually:

```bash
pipx install git+https://github.com/vericontext/rawtowise.git
```

Requires `ANTHROPIC_API_KEY` environment variable.

## Quick Start

```bash
# Initialize a project
rtw init --name "AI Research"

# Ingest sources (quote URLs with special chars like parentheses)
rtw ingest https://example.com/article
rtw ingest "https://en.wikipedia.org/wiki/Transformer_(deep_learning)"
rtw ingest paper.pdf
rtw ingest ./my-articles/

# Compile wiki
rtw compile              # incremental
rtw compile --full       # full rebuild
rtw compile --dry-run    # cost estimate only

# Query the wiki
rtw query "What are the key debates in this field?"
rtw query "Compare 3 papers" --format table
rtw query "Literature review slides" --format marp
rtw query "Deep analysis" --deep

# Health check
rtw lint

# Stats
rtw stats
```

## Project Structure

```
my-research/
├── rtw.yaml             # Configuration
├── raw/                 # Raw sources (user drops files here)
│   ├── articles/
│   └── papers/
├── wiki/                # LLM-generated wiki (auto-maintained)
│   ├── _index.md
│   ├── _sources.md
│   └── concepts/
├── output/              # Query outputs
│   └── queries/
└── .rtw/                # Internal state
```

## Configuration

`rtw.yaml`:

```yaml
version: 1
name: "My Research"

llm:
  compile: claude-sonnet-4-6
  query: claude-sonnet-4-6
  lint: claude-haiku-4-5-20251001

compile:
  strategy: incremental
  max_concepts: 200
  language: en
```

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/vericontext/rawtowise/main/uninstall.sh | bash
```

## License

MIT
