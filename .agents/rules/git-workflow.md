---
trigger: model_decision
description: "Read before branching, committing, publishing preview changes, reviewing staged paths or preparing handoff."
---
# Git workflow

Work only on preview branches (`preview/xonix-standalone-debian13`), preserving others' work and existing evidence files (`preview08-*.json`). Never modify `main` (`7e822e3e5dfe6f6e95c57fc83b24d00cd7fde661`) automatically, force push, `git reset --hard`, `git clean -fdx`, or rewrite history. Do not declare production deployment from a preview commit.

Before committing or pushing, inspect `git status` and `git diff`, verify pure LF (`\n`) line endings, executable bits on `bootstrap-preview.sh` and `install-preview.sh` (`100755`), relative Markdown links, valid YAML frontmatter on `.agents/rules/*.md`, licenses/attribution, and absence of secrets, private backups/DBs, or personal Windows paths.

Publish ordinary commits/push only within authorized preview scope. Record the exact source commit (`4c5ebd98f434723c1f424dbb4e50de3709ef1463` before docs sync) and record the final commit SHA and verified remote `HEAD` only after pushing — never invent a commit hash in advance. Confirm `main` remains unchanged.
