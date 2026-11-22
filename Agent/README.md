# Agent folder

People understand NetSilcon best from pictures, charts and the videos (see the README files,
`media/` and the website). AI agents work best from dense, exact text. This folder is the text
version of the project, kept for AI coding agents and for anyone who wants all the facts on
one page.

| File | What it is |
|---|---|
| [`SETUP_PROMPT.md`](SETUP_PROMPT.md) | Copy-paste prompt for any AI coding agent (Claude Code, Codex, Cursor, Copilot...) after you clone this repository |
| [`PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md) | Everything an agent needs: purpose, layout, both engines, the maths, protocols, results with log paths, how to verify |
| [`WORKING_RULES.md`](WORKING_RULES.md) | How work is done in this project: the order of steps, logging, honest numbers, git |
| [`MODEL_INDEX.md`](MODEL_INDEX.md) | Every trained model: shape, CRC, test vectors, accuracy, where its results are |

The root files `AGENTS.md` (read by most agents) and `CLAUDE.md` (Claude Code) point here.

**Keep it current.** When you add a model, a new network shape or a new board, update
`PROJECT_SUMMARY.md` and `MODEL_INDEX.md` in the same commit. `python tools/sync_website.py`
prints the facts of every model file, which is a quick way to check `MODEL_INDEX.md`.
