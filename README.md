# Artemis Resort & Spa — Investment Site

**Live:** https://artemisresort.com  
**Admin:** https://artemisresort.com/admin/leads?t=rovlex2025

## Structure

```
app/
  app.py              # Flask backend
  templates/
    index.html        # Main site (RU, investment presentation)
  static/
    Artemis_Resort_Investment.pdf   # PDF for download (add manually)
deploy/
  setup_server.sh     # First-time server setup (run as root)
```

## First Deploy (on server as root)

```bash
bash <(curl -s https://raw.githubusercontent.com/zaomir/artemis/main/deploy/setup_server.sh)
```

## Update (after git push)

```bash
artemis-update
```

## SSL

```bash
certbot --nginx -d artemisresort.com -d www.artemisresort.com -m ROVLEX@ROVLEX.COM --agree-tos --no-eff-email
```
