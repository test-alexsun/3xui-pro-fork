---
trigger: model_decision
description: "Read when handling keys, credentials, subscriptions, backups, logs, API access or publication content."
---
# Безопасность

Never publish real private keys (VLESS REALITY, WG/AWG Curve25519, `HeaderProtectionKey`, TLS `privkey.pem`), credentials, API tokens, Hysteria2 `auth` secrets, private panel paths, bearer subscription URLs, production SQLite, or backups. Private files require mode `0600` and directories `0700` under root ownership (`preview-panel.json`, `preview-web.json`, `preview-panel-inbounds.json`, `preview-vpn-inbounds.json`, `preview08-backup-*`, `awg/`).

Preserve existing UUIDs, keys, short IDs, and certificates without automatic regeneration. Never weaken CSRF, TLS hostname/CA verification (`allowInsecure` is forbidden across P1 and Hysteria2), `HttpOnly`/`Secure`/`SameSite=Lax` cookies, Nginx `access_log off`, ownership/SHA256 verification, or fail-closed migration rules. Prefer SQLite Online Backup with integrity check over copying active WAL databases.

Do not add unneeded certificate issuance, DNS records, port exposures, legacy protocols, or automatic provider firewall changes. Scan every staged change and evidence file for leaked secrets and personal paths. See `docs/OPERATIONS.md` and `AGENTS.md`.
