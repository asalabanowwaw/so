# Blue Knight Gate — complete Python runtime

This is the VPS/Docker version of your Blue Knight Gate project. Run **`python streamlit_app.py`** to start the panel, public TCP router, UDP gateways, native proxy cores and optional Cloudflare tunnel together. There is no Node.js or Streamlit dependency. The original JavaScript project and the earlier Streamlit frontend are separate and unchanged.

The application/server logic is Python. As in the original project, proxy cryptography and transport implementations run in native **sing-box** and **Xray** processes; **cloudflared** provides optional Argo tunneling. Python installs, checks, starts, supervises and stops these processes. Browser HTML/CSS/JavaScript remains necessary for the web interface; the original embedded assets have been retained.

## Deploy on a Linux VPS with Docker

Use a Linux VPS with Docker Engine and Compose v2. Copy this project's contents to a directory on the VPS, then:

```bash
cp .env.example .env
nano .env
```

Set `DOMAIN` to the VPS's public DNS name or public IP. Optionally set `PANEL_PASSWORD` to a password of at least eight characters. Keep `REALITY_TARGET=www.google.com` unless you have checked another reachable TLS 1.3 target.

```bash
docker compose up -d --build
docker compose logs -f
```

Open **`https://YOUR_DOMAIN/knight`**, or **`http://YOUR_VPS_IP:8080/knight`** during initial setup. The image runs as UID 10001 and Compose allows it to bind port 443 without a privileged container. WireGuard uses sing-box's userspace network stack; this configuration does not require a host TUN interface or NET_ADMIN.

If `PANEL_PASSWORD` is blank, read the first-time setup key:

```bash
docker compose exec blue-knight cat /data/setup-key.txt
```

Enter that key on the setup page and create a password. This prevents an anonymous visitor from claiming a new installation. The key and generated identities stay in the named Docker data volume.

### Public ports and firewall

Allow the ports for the protocols you enable in both the VPS provider firewall and the host firewall:

- **443/TCP**: TLS web panel, TLS WebSocket/HTTPUpgrade/gRPC/XHTTP, REALITY and ShadowTLS.
- **8080/TCP**: plain HTTP panel, plain WebSocket/HTTPUpgrade/gRPC/XHTTP, and optional authenticated SOCKS5/HTTP CONNECT.
- **8388/TCP + UDP**: Shadowsocks.
- **51820/UDP**: WireGuard.
- **8443/UDP**: Hysteria2, when enabled.
- **8444/UDP**: TUIC, when enabled.

Both shared TCP listeners can recognize plain HTTP and TLS. Generated links select 8080 for cleartext transports and 443 for TLS/REALITY/ShadowTLS. Change ports in `.env`; Compose uses the same values for host and container mappings. Disabled protocols do not create listeners even though their ports are listed in Compose.

Use a direct DNS record for REALITY, ShadowTLS and UDP protocols. A normal HTTP CDN/reverse proxy cannot carry their native traffic. WebSocket/HTTPUpgrade/XHTTP can use a suitable HTTP reverse proxy; gRPC additionally requires end-to-end HTTP/2 support.

If a reverse proxy terminates HTTPS for the panel, set `PUBLIC_BASE_URL` to its exact public HTTPS origin so sign-in origin checks and secure cookies use that origin. Arbitrary client-supplied forwarded headers are not trusted. Cloudflare tunnel hostnames discovered/configured by the supervisor are recognized automatically.

### Trusted TLS certificates

The app initially creates a self-signed certificate. Your browser will warn, and generated TLS node profiles explicitly allow that certificate. To use a trusted certificate:

1. Put the PEM certificate and key under `./certs` (for example, `fullchain.pem` and `privkey.pem`). Make them readable by container UID 10001.
2. Uncomment the `./certs:/certs:ro` mount in `compose.yaml`.
3. Set `TLS_CERT=/certs/fullchain.pem`, `TLS_KEY=/certs/privkey.pem`, `LINK_INSECURE=false`, and a matching `DOMAIN` in `.env`.
4. Run `docker compose up -d --force-recreate`.

Certificate issuance/renewal is external to this app. Restart/recreate the container after renewal so both Python TLS and native QUIC listeners load the new certificate. Public subscription links should normally use the trusted HTTPS address; `PUBLIC_BASE_URL` overrides the origin shown by the panel if needed.

## Included functionality

- The original panel design, themes, images, node cards, copy actions and QR dialogs. QR images are generated locally; connection credentials are no longer sent to a third-party QR service.
- First-time password setup, salted scrypt password hashes, signed HttpOnly sessions, login rate limiting, subscription tokens, and protected traffic mutations.
- VLESS, VMess and Trojan over WebSocket, with cleartext and TLS profiles.
- VLESS, VMess and Trojan over HTTPUpgrade, with cleartext and TLS profiles.
- VLESS gRPC cleartext/TLS and Trojan gRPC TLS, multiplexed by HTTP/2 stream. Trojan uses a distinct service name to coexist with VLESS.
- VLESS REALITY and VLESS over ShadowTLS v3, routed by ClientHello SNI.
- VLESS XHTTP and Shadowsocks over WebSocket, served by Xray.
- Shadowsocks TCP/UDP, userspace WireGuard, Hysteria2 and TUIC UDP, and authenticated TCP SOCKS5/HTTP CONNECT.
- Raw/Base64 subscription endpoints, Mihomo/Clash Meta YAML, sing-box client JSON, Xray client JSON and WireGuard `.conf` downloads.
- Byte counts and live rates at the Python TCP/UDP gateways, daily/monthly/all-time history, UTC month rollover, monthly baseline adjustment and reset.
- Persisted UUID, REALITY/WireGuard keypairs, protocol passwords, panel password, subscription token and traffic counters.
- Config validation by the real cores before startup, bounded process restarts, graceful shutdown, engine logs, and readiness checks. A stopped core's nodes are omitted from subscriptions.
- Optional Cloudflare quick or named tunnel with an extra VLESS WebSocket Argo node. Hysteria2/TUIC, SOCKS5, HTTP CONNECT and ShadowTLS are enabled through `.env` switches.

The original project advertised some configurations that its engines could silently drop. This version fails startup if an enabled engine configuration is rejected, rather than removing features silently.

### Client format compatibility

Raw/Base64 subscriptions default to broadly compatible URI types. Add `?compat=full` to include specialized schemes such as WireGuard, TUIC and ShadowTLS. For links that already contain `?token=...`, append `&compat=full`.

- Import WireGuard's **`.conf` file** into the official WireGuard client. The generated WireGuard profile routes IPv4; IPv6 addressing/routing is not configured.
- Import ShadowTLS's **sing-box JSON** to preserve its VLESS-over-ShadowTLS chain; a bare ShadowTLS URI does not encode that complete chain.
- Use Xray/v2rayN for **XHTTP**. The pinned sing-box version does not implement it, so it is omitted from sing-box JSON.
- HTTPUpgrade and XHTTP are omitted from Clash YAML rather than emitting unverified transport syntax.
- sing-box clients need **v2ray-plugin** installed for the Shadowsocks-WS entry, or can use the exported Xray version of that node instead.
- Xray JSON contains Xray-compatible protocols; WireGuard, TUIC, Hysteria2 and ShadowTLS use the other export formats.
- Native SOCKS5's optional listener exposes TCP proxying. It does not expose SOCKS5 UDP ASSOCIATE through the shared TCP port.

The Xray client JSON lists available outbounds with the first as the default; select/reorder the desired outbound in your client. sing-box and Clash files include a selectable group. Every file/URI contains connection credentials and should be treated as private.

## API and subscriptions

The default panel is `/knight`; `PANEL_PATH` changes its prefix. Existing route shapes are retained:

```text
/knight/login                 password sign-in / first-time setup
/knight/logout                clear browser session
/health                       authenticated status and nodes
/healthz                      readiness without credentials (200 or 503)
/knight/raw                   raw compatible node URIs
/knight/base64                 Base64 subscription
/knight/sub                    Base64 subscription
/knight/clash                  Mihomo YAML
/knight/sb/raw                 sing-box client JSON
/knight/sb/base64              Base64 sing-box JSON
/knight/xray/raw               Xray client JSON
/knight/xray/base64            Base64 Xray JSON
/knight/wg.conf                WireGuard client profile
/knight/api/traffic            live/history snapshot (session only)
/knight/api/traffic/baseline   POST {"gb": 10} (session + X-BK-Req: 1)
/knight/api/traffic/reset      POST (session + X-BK-Req: 1)
```

Subscription downloads accept the browser session or `?token=YOUR_SUB_TOKEN`; traffic mutations require the browser session. The panel obtains its token from the authenticated health response. Root aliases `/sub`, `/base64`, `/clash`, `/sb` and `/wg.conf` are supported.

## Optional Cloudflare tunnel

For a quick tunnel, set `ENABLE_ARGO=true` with `ARGO_AUTH` and `ARGO_DOMAIN` blank. Read the generated `trycloudflare.com` hostname from `/data/argo.log`; it also appears as the Argo node after discovery. Quick-tunnel hostnames change when restarted.

For a named tunnel, set `ENABLE_ARGO=true`, `ARGO_DOMAIN` to its public hostname, and `ARGO_AUTH` to its tunnel token. Configure that hostname in Cloudflare to forward to `http://127.0.0.1:8080` (adjust for your `PORT`). The token is passed to cloudflared through its environment, not command-line arguments or logs. Native REALITY, ShadowTLS and UDP connections continue using the VPS address, not the tunnel hostname.

## Run directly on a VPS

Python **3.11+** is required. From this folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Edit DOMAIN, credentials and switches.
.venv/bin/python streamlit_app.py --install-engines
.venv/bin/python streamlit_app.py --check --no-download
.venv/bin/python streamlit_app.py --no-download
```

Port 443 requires root, an OS binding capability, or a higher `TLS_PORT` on a native Linux install. Docker Compose configures low-port access for its nonroot process. For a persistent native install, set `BK_DATA_DIR=/var/lib/blue-knight`, ensure the service user owns it, and use your service manager to restart `streamlit_app.py`.

On Windows use `.venv\Scripts\python.exe` instead of `.venv/bin/python`. Ctrl+C stops the runtime and children. For a service wrapper or automated test, `--stop-file /path/to/stop` gracefully stops the runtime when that file is created; remove the file before the next start.

Native releases are pinned to sing-box **1.11.15**, Xray **25.6.8**, and cloudflared **2026.10.0**. Docker installs them at build time in `/opt/blue-knight/bin`; native runs use `BK_DATA_DIR/bin`. `SINGBOX_BIN`, `XRAY_BIN` and `CLOUDFLARED_BIN` can select preinstalled binaries. Version overrides require revalidation because engine schemas change. Optional `SINGBOX_SHA256`, `XRAY_SHA256` and `CLOUDFLARED_SHA256` verify the corresponding downloaded release archive/binary.

## Persistence, backups and maintenance

```bash
docker compose logs --tail=100
docker compose exec blue-knight python streamlit_app.py --check --no-download
docker compose restart
```

Data is in the `knight-data` named volume at `/data`: `state.json`, `auth.json`, `traffic.json`, certificates, engine configs and logs. Rebuilding the image keeps this volume. **`docker compose down -v` deletes it**, including keys and counters; use `docker compose down` to keep the data.

Back up the complete `/data` directory while the service is stopped. Restore it before starting a replacement installation. To reuse an original server's identities, copy its `state.json` into the new data directory before first startup, then re-download the new client profiles. Panel cookies/authentication are newly implemented; set `PANEL_PASSWORD` or use the new setup flow. Do not copy old generated core configs over the new runtime's files.

If `PANEL_PASSWORD` is set in `.env`, it takes precedence on each startup. Edit/remove it there when changing the password. A password change invalidates existing sessions. `SUB_TOKEN` behaves similarly for subscriptions. Remove temporary `RESET_PANEL_PASSWORD=true` after using it.

Traffic values include transport overhead and are not a VPS provider's billing meter. The allowance is informational, not an enforced quota. TCP/UDP relay counts survive a clean shutdown; the last 30 seconds can be lost after an abrupt process/container kill. UDP association counts and proxy-session counts are operational estimates.

## Verification

```bash
python -m unittest discover -s tests -v
python streamlit_app.py --check --no-download
```

The unit/integration suite tests authentication, token/session separation, CSRF checks, rate limits, startup/readiness, route aliases, key persistence, monthly accounting, local QR generation, TCP half-close forwarding and per-client UDP relays.

An additional real-core test starts a temporary full runtime and proxy clients, then transfers data to a local HTTP fixture:

```bash
python tests/native_smoke.py --singbox-bin /path/to/sing-box --xray-bin /path/to/xray --external-handshakes
```

`--external-handshakes` enables REALITY/ShadowTLS handshakes with the configured decoy hosts; payload traffic still goes to the local fixture. Without that flag these two tests are skipped. The fixture temporarily binds an ephemeral HTTP port on all local interfaces so userspace WireGuard can reach it; it serves only synthetic test data. Logs/configs are removed on exit unless `--keep` is supplied. `--keep` writes generated test credentials under ignored `.validation/native-debug`.

Validated locally on Windows with the actual pinned cores: **26 native protocol/profile tests passed**, including 2 MiB upload/download checks for gRPC/XHTTP. The Docker/Compose files are supplied for Linux deployment; this workstation does not have Docker, so a Linux container build/launch has not been verified here. Cloudflared's pinned binary/version was verified; a live Cloudflare account/tunnel has not been configured or tested.

## Upstream references

- sing-box configuration: https://sing-box.sagernet.org/configuration/
- Xray configuration: https://xtls.github.io/en/config/
- Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/

The original panel branding/assets belong to your source project. Native cores retain their upstream licenses; see their release repositories.
