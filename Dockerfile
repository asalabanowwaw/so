FROM node:22-bookworm-slim

# Engine archives require tar/gzip; HTTPS downloads require the CA store.
# tini forwards shutdown signals and reaps child processes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tar gzip tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY --chown=node:node index.js ./index.js
RUN mkdir -p /data && chown node:node /app /data

ENV NODE_ENV=production \
    PORT=3000 \
    BK_DATA_DIR=/data \
    LINK_TLS=true \
    LINK_PORT=443

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD ["node", "-e", "const h=require('node:http');const p=(process.env.PANEL_PATH||process.env.SUB_PATH||'knight').replace(/^\\//,'');const r=h.get({host:'127.0.0.1',port:process.env.PORT||3000,path:'/'+p+'/login'},s=>{s.resume();process.exit(s.statusCode===200?0:1)});r.setTimeout(4000,()=>{r.destroy();process.exit(1)});r.on('error',()=>process.exit(1));"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["node", "index.js"]
