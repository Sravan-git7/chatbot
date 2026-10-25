# Secrets — not committed

Place the backend token here only on the staging host, never in Git.

```bash
# Generate 32-256 ASCII token (no whitespace, no newline)
python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters+string.digits+'-_.') for _ in range(64)))" > secrets/sura_api_token.txt
chmod 600 secrets/sura_api_token.txt
```

Production: use external secret manager (AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, Vault). Configure `docker-compose.yml` secrets as `external: true`.

Never log `SURA_API_TOKEN`; never echo it in reports; never expose via /health or /ready.
