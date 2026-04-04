# Testing Guide

End-to-end walkthrough to verify the full `ingest → compile → query → lint` cycle.

> Run these in a **separate directory** (not inside the project repo) to simulate a real user install.

---

## 1. Setup

```bash
mkdir -p ~/playground/rtw-test && cd ~/playground/rtw-test

# Install
curl -fsSL https://raw.githubusercontent.com/vericontext/rawtowise/main/install.sh | bash

# Verify
rtw version
```

## 2. Initialize

```bash
rtw init --name "Test KB"
# → Creates rtw.yaml, directories, prompts for API key
```

## 3. Ingest Sources

```bash
rtw ingest https://en.wikipedia.org/wiki/Retrieval-augmented_generation
rtw ingest https://en.wikipedia.org/wiki/Large_language_model
rtw ingest "https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)"
rtw ingest https://en.wikipedia.org/wiki/Word_embedding
rtw ingest https://en.wikipedia.org/wiki/Prompt_engineering
```

> **Note:** Quote URLs containing parentheses to avoid shell parsing errors.

```bash
# Verify
ls raw/articles/
rtw stats
```

## 4. Compile

```bash
# Preview cost
rtw compile --dry-run

# Compile (parallel article generation, ~30s for 5 sources)
rtw compile
```

```bash
# Verify
ls wiki/concepts/
cat wiki/_index.md
```

## 5. Query

```bash
# Answers stream in real-time
rtw query "What is the relationship between RAG and LLMs?"

# Table format
rtw query "Compare RAG vs fine-tuning" --format table

# Check saved output
ls output/queries/
```

## 6. Lint

```bash
rtw lint
# → Health score, contradictions, gaps, suggested questions
```

## 7. Incremental Compile

```bash
# Add another source
rtw ingest "https://en.wikipedia.org/wiki/Fine-tuning_(deep_learning)"

# Recompile (detects new source automatically)
rtw compile

# Or force full rebuild
rtw compile --full
```

## 8. View in Obsidian / VSCode

Open `wiki/` folder as:
- **Obsidian vault** — graph view shows concept connections
- **VSCode workspace** with [Foam](https://marketplace.visualstudio.com/items?itemName=foam.foam-vscode) extension

## Cleanup

```bash
rm -rf ~/playground/rtw-test
```
