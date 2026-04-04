# Testing Guide

End-to-end test from a clean directory to verify the full user flow.

## Setup

```bash
# 1. Create a test directory (outside the project)
mkdir -p ~/dev/personal/playground/rtw-test
cd ~/dev/personal/playground/rtw-test

# 2. Install (simulates real user install)
curl -fsSL https://raw.githubusercontent.com/vericontext/rawtowise/main/install.sh | bash

# 3. Verify
rtw version
```

## Test: Full Cycle

```bash
# Step 1 — Init (will prompt for API key if not set)
rtw init --name "Test KB"

# Step 2 — Ingest a few sources
rtw ingest https://en.wikipedia.org/wiki/Retrieval-augmented_generation
rtw ingest https://en.wikipedia.org/wiki/Large_language_model
rtw ingest https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)
rtw ingest https://en.wikipedia.org/wiki/Word_embedding
rtw ingest https://en.wikipedia.org/wiki/Prompt_engineering

# Step 3 — Check what got collected
ls raw/articles/
rtw stats

# Step 4 — Dry run (see cost estimate before compiling)
rtw compile --dry-run

# Step 5 — Compile
rtw compile

# Step 6 — Inspect the generated wiki
ls wiki/concepts/
cat wiki/_index.md

# Step 7 — Query
rtw query "What is the relationship between RAG and LLMs?"
rtw query "Compare RAG vs fine-tuning" --format table

# Step 8 — Check query output was saved
ls output/queries/

# Step 9 — Lint
rtw lint

# Step 10 — Stats again (should show growth)
rtw stats
```

## Test: Incremental Compile

```bash
# Add another source after initial compile
rtw ingest https://en.wikipedia.org/wiki/Fine-tuning_(deep_learning)

# Should only process the new source
rtw compile

# Full rebuild
rtw compile --full
```

## Cleanup

```bash
# Remove test directory when done
rm -rf ~/dev/personal/playground/rtw-test
```
