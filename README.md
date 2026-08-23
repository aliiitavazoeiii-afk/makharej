# Kharj — Personal Expense Dashboard

A Persian RTL personal expense manager with a premium dark dashboard, Jalali dates and lightweight self-hosted deployment.

## Features

- Fast daily expense entry
- Dark responsive dashboard inspired by modern fintech UIs
- Jalali date input and display
- Categories, monthly category budgets and recurring bills
- 7-day trend chart and category donut chart without external JS/CDN dependencies
- Reports and CSV export
- Single-admin login
- SQLite persistence in a Docker volume
- Nginx reverse proxy + automatic Let's Encrypt attempt
- Isolated deployment that can coexist with the existing VPN Control Center

## One-line install

Run on the same Ubuntu/Debian management VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/aliiitavazoeiii-afk/makharej/main/install.sh | sudo bash
```

Default domain: `kharj.boro2film.top`.

The installer binds Kharj only to `127.0.0.1` on a free port starting at `8091`; the existing VPN Control Center normally uses port `8080`, so the two applications do not collide. Nginx routes the domain to Kharj.

## Update

Run the same one-line installer again. The `.env` credentials are preserved and the Docker volume containing `kharj.db` is not deleted.

## Manual development

```bash
cp .env.example .env
# edit secrets in .env
docker compose up -d --build
```

Open `http://127.0.0.1:8091` from the server or put it behind a reverse proxy.
