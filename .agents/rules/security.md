---
trigger: model_decision
description: "Read when handling keys, credentials, subscriptions, backups, logs, API access or publication content."
---
# Безопасность

Never publish real private keys, credentials, API tokens, private panel paths, bearer subscription URLs, production SQLite or backup. Private files require mode0600 and directories0700 under root ownership. Use sanitized structural evidence; inspect staged changes before commit/push.

Preserve existing UUID/keys/short IDs/certificates and do not regenerate identities automatically. Do not weaken CSRF, hostname verification, ownership/hash checks or fail-closed migration rules. Prefer consistent SQLite Online Backup with verified private manifest to copying an active DB.

Do not add unneeded certificate issuance, DNS records, port exposures, legacy protocols or automatic provider firewall changes. See `docs/OPERATIONS.md` and AGENTS.md.
