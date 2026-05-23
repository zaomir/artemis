#!/bin/bash
# Apply no-cache headers to nginx config for artemisresort.com
# Run as root on server

CONF=/etc/nginx/sites-available/artemisresort.com

# Update static location to disable caching
python3 - << 'PYEOF'
import re

with open('/etc/nginx/sites-available/artemisresort.com', 'r') as f:
    content = f.read()

# Replace static location
old_pattern = r'location /static/\s*\{[^}]+\}'
new_block = """location /static/ {
        alias /var/www/artemis/app/static/;
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0";
        add_header Pragma "no-cache";
    }"""

content = re.sub(old_pattern, new_block, content)

with open('/etc/nginx/sites-available/artemisresort.com', 'w') as f:
    f.write(content)
print("nginx config updated")
PYEOF

nginx -t && systemctl reload nginx && echo "nginx reloaded OK"
