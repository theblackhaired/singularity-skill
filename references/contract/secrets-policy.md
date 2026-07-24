# Secrets policy

- Store the bearer token only in ignored `config.json`.
- Load configuration only through `config.py`.
- Never write configuration from cache, doctor, metadata, or probe code.
- Never put live tokens or user content in fixtures, logs, snapshots, examples,
  or committed API-shape artifacts.
- Redact bearer and authorization values from HTTP error bodies before
  returning or logging them.
- Keep `--doctor`, `--verify-api`, `--verify-cache`, and metadata checks
  read-only.
- Rotate a token by replacing the local `token` value; no cache migration is
  required.
