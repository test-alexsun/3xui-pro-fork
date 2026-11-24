---
trigger: model_decision
description: "Read before branching, committing, publishing preview changes, reviewing staged paths or preparing handoff."
---
# Git workflow

Work on preview branches, preserve others' work and evidence. Do not modify main automatically, force push, reset hard, clean untracked files or rewrite history. Do not declare production-stable release without corresponding acceptance.

Before publication review staged diff, secrets/private data, executable installer bits, relative Markdown links, attribution/licenses and docs/source consistency. Exclude private DB/backups/tokens/configs without deleting historical evidence blindly.

Publish ordinary commits/push only within authorized preview scope. Record base/new commit, verify remoteHEAD and published files and confirm main unchanged. A local commit is not publication and a published preview is not deployment. Update `docs/PROJECT_STATUS.md` and final evidence with actual outcomes only.
