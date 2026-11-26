"""Verify the backend serves the built SPA and static assets."""

import re

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

r = client.get("/")
assert r.status_code == 200, r.status_code
assert "text/html" in r.headers.get("content-type", ""), r.headers
assert 'id="root"' in r.text
print("PASS root serves index.html")

m = re.search(r'/assets/[^"\']+', r.text)
assert m, "no asset reference found in index.html"
asset_url = m.group(0)
r2 = client.get(asset_url)
assert r2.status_code == 200, (asset_url, r2.status_code)
print(f"PASS asset served: {asset_url} ({r2.headers.get('content-type')})")

r3 = client.get("/findings")
assert r3.status_code == 200 and 'id="root"' in r3.text
print("PASS client-side route falls back to index.html")

r4 = client.get("/api/does-not-exist")
assert r4.status_code == 404
print("PASS unknown API path returns 404 (not SPA)")

print("\nSPA SMOKE: all checks passed")
