# Blue Knight Panel · Deployment tests

Personal deployment test repository. The shared Hostless edition is [BlueKnightNet/Blue-Knight-Panel-Hostless](https://github.com/BlueKnightNet/Blue-Knight-Panel-Hostless).

## MS HOST / Meera Solution

This is a **plain Node.js server**, not a Next.js application. A generated Next.js Dockerfile that runs `npm run build` and copies `.next/standalone` cannot deploy this project.

Use the repository's Dockerfile:

| Setting | Value |
| --- | --- |
| Repository | `asalabanowwaw/so` |
| Branch | `main` |
| Framework | **Docker** |
| Root / build context | `/` |
| Dockerfile | `Dockerfile` at the repository root |
| Container port | `3000` |
| Build command override | Leave empty |
| Start command override | Leave empty; the image runs `node index.js` |
| Persistent volume, if available | `/data`, writable by UID/GID `1000` |

If the current project is configured as Next.js, change the framework to Docker. If the dashboard does not allow changing it, create a Docker project connected to this repository. See the official [MS HOST Docker deployment guide](https://host.meerasolution.com/blogs/how-to-deploy-docker).

The image installs production npm dependencies and archive tools, then runs as the unprivileged `node` user. It defaults to internal port `3000` and public HTTPS/TLS links on `443`. If the platform assigns another `PORT`, match its internal routing to that value. Engine binaries are downloaded on first startup; allow time for initialization.

Open `https://YOUR-APP-DOMAIN/knight` to create the password, then refresh the subscription. The panel learns the public hostname from the request. It does not contain a fixed Meera application domain. Keep `/data` persistent to preserve the UUID, password, subscription token, certificates, and engine files.

Alternatively, choose the platform's **Node.js** framework, start with `npm start`, and configure its internal port plus `LINK_TLS=true` and `LINK_PORT=443` for HTTPS-edge access. Do not select Next.js or add a fake build script to bypass its template.

## Container checks

The [container workflow](.github/workflows/container-check.yml) builds the image on Linux, waits for the login page, and checks sing-box/Xray listeners. Building an image successfully is separate from confirming the hosting provider supports the proxy transports.

## Channels

- [YouTube · BlueKnight-Net](https://www.youtube.com/@BlueKnight-Net)
- [Telegram · BlueKnight_Net](https://t.me/BlueKnight_Net)
