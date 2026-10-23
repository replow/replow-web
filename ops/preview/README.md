# Isolated preview

Hosts: www.preview.replow.org, account.preview.replow.org, admin.preview.replow.org. API proxied at /v1 to 127.0.0.1:8814; database replow_preview; session silune_preview_sso on .preview.replow.org. Uploads use isolated local storage; external storage writes are disabled.

Preview frontend branches: preview-www, preview-admin, preview-account. Initial builds use GitHub Actions prereleases ignored by the production deployer. The preview content publish button uses a path-triggered systemd worker, builds the isolated source and dependencies on the server, and atomically switches /data/replow-preview/www. Build failures preserve the prior preview. Its resource limits and files are separate from production. Secrets remain only in the private preview environment file; never commit them.

Run ops/preview/test_integration.py with the deployed Python venv only against the isolated DB. It creates temporary identities and cleans test content. Browser QA uses temporary credentials stored only in a private runtime file and removed after verification.
