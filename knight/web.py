import asyncio
import base64
import html
import hmac
import json
import math
import logging
import secrets
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import qrcode
import qrcode.image.svg
from aiohttp import web

from .config import host
from .links import Links
from .storage import write_json

STATIC = Path(__file__).resolve().parents[1] / 'static'


def make_app(cfg, state, auth, traffic, supervisor):
    started = time.monotonic()
    panel = '/' + cfg.panel
    setup_key_path = cfg.data / 'setup-key.txt'
    if not auth.data.get('hash'):
        if not setup_key_path.exists():
            setup_key_path.write_text(cfg.env.get('SETUP_KEY') or secrets.token_urlsafe(32), encoding='utf-8')
            setup_key_path.chmod(0o600)
    setup_key = cfg.env.get('SETUP_KEY') or (setup_key_path.read_text().strip() if setup_key_path.exists() else '')

    def session(request):
        return auth.valid(request.cookies.get('bk_session', ''))

    def authorized(request):
        token = request.query.get('token', '')
        return session(request) or bool(auth.data.get('hash') and token and hmac.compare_digest(token, auth.data['subToken']))

    def scheme(request):
        # These are configured/discovered public origins, not arbitrary forwarded headers.
        if cfg.public_base:
            public = urlsplit(cfg.public_base)
            if public.netloc == request.host:
                return public.scheme
        if supervisor.argo_domain and request.host == supervisor.argo_domain:
            return 'https'
        return request.headers.get('X-BK-Scheme', request.scheme)

    def require_session(request):
        if not session(request):
            raise web.HTTPUnauthorized(text='Login required')

    def same_origin(request):
        origin = request.headers.get('Origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc != request.host or parsed.scheme != scheme(request):
                logging.getLogger('knight.web').warning('Rejected Origin %r; expected %s://%s', origin, scheme(request), request.host)
                raise web.HTTPForbidden(text='Invalid origin')

    @web.middleware
    async def security(request, handler):
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc
        if isinstance(response, web.HTTPException):
            exception_response = response
            response = web.Response(body=exception_response.body, status=exception_response.status,
                                    reason=exception_response.reason, headers=exception_response.headers)
            response.cookies.update(exception_response.cookies)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        if not request.path.startswith(('/knight-assets/', '/assets/')):
            response.headers['Cache-Control'] = 'no-store'
        # The TCP router injects trusted source headers into one request per connection.
        response.force_close()
        return response

    app = web.Application(middlewares=[security], client_max_size=10240)

    async def qr(request):
        require_session(request)
        value = request.query.get('data', '')
        if not value or len(value) > 4096:
            raise web.HTTPBadRequest(text='Invalid QR payload')
        try:
            image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
            return web.Response(body=image.to_string(), content_type='image/svg+xml')
        except qrcode.exceptions.DataOverflowError:
            raise web.HTTPBadRequest(text='This configuration is too large for a QR code') from None

    def links(request):
        if not cfg.domain and not cfg.force_host:
            learned = host(request.host)
            if learned and learned != state.get('publicHost'):
                state['publicHost'] = learned
                write_json(cfg.data / 'state.json', state)
        return Links(cfg, state, supervisor.status(), supervisor.argo_domain)

    async def panel_view(request):
        if not session(request):
            raise web.HTTPFound(panel + '/login')
        body = (STATIC / 'index.html').read_text(encoding='utf-8').replace('/knight/', panel + '/')
        body = body.replace("Replit's <b>Account &rarr; Usage</b> page is the real meter.",
                            'Measured at the Python TCP/UDP gateways; transport overhead is included.')
        return web.Response(text=body, content_type='text/html')

    def login_page(message='', status=200):
        setup = not auth.data.get('hash')
        extra = ('<label>Setup key / کلید راه‌اندازی<input name="setup_key" type="password" required autocomplete="off"></label>'
                 '<p>Read <code>setup-key.txt</code> in your server data directory.</p>' if setup else '')
        confirm = '<label>Confirm password / تکرار رمز<input name="confirm" type="password" minlength="8" required autocomplete="new-password"></label>' if setup else ''
        title = 'Create your panel password' if setup else 'Sign in to your gate'
        body = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | Blue Knight Gate</title><link rel="icon" href="/knight-assets/logo.png">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#080e1c url('/knight-assets/bg.jpg') center/cover fixed;color:#ecf5ff;font:16px system-ui}}*{{box-sizing:border-box}}main{{width:min(440px,92vw);margin:35px 0;padding:32px;border-radius:24px;border:1px solid #365477;background:#0b162bf0;box-shadow:0 25px 80px #0008}}img{{width:68px}}h1{{font-size:28px}}label{{display:block;margin:18px 0 6px;font-size:14px}}input{{display:block;width:100%;padding:13px;margin-top:8px;border-radius:9px;border:1px solid #365477;background:#101e34;color:white;font:inherit}}button{{width:100%;padding:14px;background:#5bbaff;border:0;border-radius:10px;font-weight:700;margin-top:20px;cursor:pointer}}p{{color:#abc1d8;font-size:13px}}.error{{color:#ffb4af}}a{{color:#7dcfff}}</style></head><body><main>
<img src="/knight-assets/logo.png" alt="Blue Knight"><p>BLUE KNIGHT GATE · PYTHON</p><h1>{title}</h1><p>ورود به پنل بلو نایت</p><p class="error">{html.escape(message)}</p>
<form method="post" action="{panel}/login">{extra}<label>Password / رمز عبور<input name="password" type="password" required minlength="{8 if setup else 1}" maxlength="1024" autocomplete="{'new-password' if setup else 'current-password'}"></label>{confirm}<button type="submit">{'Create password' if setup else 'Sign in'}</button></form><p>Private session · <a href="https://t.me/BlueKnight_Net">Blue Knight Net</a></p></main></body></html>'''
        return web.Response(text=body, content_type='text/html', status=status)

    async def login(request):
        if request.method == 'GET':
            if session(request):
                raise web.HTTPFound(panel)
            return login_page()
        same_origin(request)
        ip = request.headers.get('X-BK-Client-IP', request.remote or 'unknown')
        if auth.blocked(ip):
            return login_page('Too many attempts. Try again in 15 minutes.', 429)
        data = await request.post()
        password = str(data.get('password', ''))
        if len(password) > 1024:
            return login_page('Password is too long.', 400)
        if not auth.data.get('hash'):
            if not setup_key or not hmac.compare_digest(str(data.get('setup_key', '')), setup_key):
                auth.failed(ip)
                return login_page('Wrong setup key.', 401)
            if len(password) < 8 or password != str(data.get('confirm', '')):
                return login_page('Use at least 8 characters and matching passwords.', 400)
            await asyncio.to_thread(auth.set_password, password)
        elif not await asyncio.to_thread(auth.verify, password):
            auth.failed(ip)
            return login_page('Wrong password.', 401)
        auth.failures.pop(ip, None)
        response = web.HTTPFound(panel)
        response.set_cookie('bk_session', auth.session(), httponly=True, samesite='Lax',
                            secure=scheme(request) == 'https', max_age=30 * 86400, path='/')
        return response

    async def logout(request):
        response = web.HTTPFound(panel + '/login')
        response.del_cookie('bk_session', path='/')
        return response

    async def health(request):
        if not authorized(request):
            raise web.HTTPUnauthorized()
        generator = links(request)
        is_tls = scheme(request) == 'https'
        public_port = cfg.tls_port if is_tls else cfg.port
        base = cfg.public_base or f'{"https" if is_tls else "http"}://{request.host}'
        return web.json_response({'ok': True, 'brand': 'Blue Knight Net', 'product': 'Blue Knight Gate Python',
            'uptime': time.monotonic() - started, 'publicPort': public_port,
            'host': generator.host, 'domain': cfg.domain or generator.host, 'forceHost': cfg.force_host,
            'publicBaseUrl': base, 'subBase': '', 'forceHttps': is_tls, 'location': cfg.env.get('LOCATION', 'VPS / Docker'),
            'engines': supervisor.status(), 'subToken': auth.data['subToken'], 'nodes': generator.public_nodes()})

    async def readiness(request):
        status = supervisor.status()
        ready = status['singbox'] and (status['xray'] if cfg.enable['xhttp'] or cfg.enable['ssWs'] else True)
        return web.json_response({'ok': ready, 'engines': status}, status=200 if ready else 503)

    async def subscription(request):
        if not authorized(request):
            raise web.HTTPUnauthorized()
        generator = links(request)
        fmt = request.match_info.get('format', request.path.rsplit('/', 1)[-1])
        compat = request.query.get('compat', 'v2ray')
        filename, content_type = 'BlueKnight.txt', 'text/plain'
        if fmt in ('raw', 'base64', 'sub'):
            content = generator.raw(compat)
            if fmt != 'raw':
                content = base64.b64encode(content.encode()).decode()
        elif fmt in ('clash', 'clash.yaml'):
            content, filename, content_type = generator.clash(), 'BlueKnight.yaml', 'text/yaml'
        elif fmt in ('sb', 'sb/raw', 'sb/base64'):
            content = json.dumps(generator.singbox(), ensure_ascii=False, indent=2)
            filename, content_type = 'sing-box-client.json', 'application/json'
            if fmt.endswith('base64'):
                content = base64.b64encode(content.encode()).decode()
                content_type = 'text/plain'
        elif fmt in ('xray/raw', 'xray/base64'):
            content = json.dumps(generator.xray(), ensure_ascii=False, indent=2)
            filename, content_type = 'xray-client.json', 'application/json'
            if fmt.endswith('base64'):
                content = base64.b64encode(content.encode()).decode()
                content_type = 'text/plain'
        elif fmt in ('wg.conf', 'wireguard.conf'):
            if not cfg.enable['wireguard'] or not supervisor.status()['singbox']:
                raise web.HTTPNotFound(text='WireGuard is disabled or its engine is stopped')
            content, filename = generator.wireguard_conf(), 'wg0.conf'
        else:
            raise web.HTTPNotFound()
        return web.Response(text=content, content_type=content_type, headers={
            'Content-Disposition': f'attachment; filename="{filename}"', 'Profile-Update-Interval': '24',
            'Subscription-Userinfo': 'upload=0; download=0; total=0; expire=0'})

    async def traffic_api(request):
        require_session(request)
        if request.method == 'POST':
            same_origin(request)
            if request.headers.get('X-BK-Req') != '1':
                raise web.HTTPForbidden()
            if request.path.endswith('/reset'):
                traffic.reset()
            else:
                try:
                    body = await request.json()
                    value = float(body['gb'])
                    if not math.isfinite(value) or not 0 <= value <= 1e6:
                        raise ValueError()
                except (ValueError, TypeError, KeyError):
                    raise web.HTTPBadRequest(text='Invalid GiB value') from None
                traffic.baseline(value)
        return web.json_response(traffic.snapshot())

    video_cache = {'at': 0, 'value': {'ok': True, 'videoId': 'rFmtnT0xeWg',
        'url': 'https://www.youtube.com/watch?v=rFmtnT0xeWg',
        'thumbnail': 'https://i.ytimg.com/vi/rFmtnT0xeWg/hqdefault.jpg', 'title': 'Blue Knight Net'}}

    async def latest_video(request):
        if time.monotonic() - video_cache['at'] > 300:
            video_cache['at'] = time.monotonic()
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
                    async with client.get('https://www.youtube.com/feeds/videos.xml?channel_id=UCOUsLDQyNHhp_g7-jeZAJyg') as response:
                        response.raise_for_status()
                        data = await response.content.read(512 * 1024)
                root = ET.fromstring(data)
                entry = root.find('{http://www.w3.org/2005/Atom}entry')
                if entry is not None:
                    video_id = entry.findtext('{http://www.youtube.com/xml/schemas/2015}videoId')
                    title = entry.findtext('{http://www.w3.org/2005/Atom}title')
                    if video_id:
                        video_cache['value'] = {'ok': True, 'videoId': video_id,
                            'url': f'https://www.youtube.com/watch?v={video_id}',
                            'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg', 'title': title or 'Blue Knight Net'}
            except (aiohttp.ClientError, asyncio.TimeoutError, ET.ParseError):
                pass
        return web.json_response(video_cache['value'])

    async def asset(request):
        filename = request.match_info['file']
        aliases = {'logo.jpg': 'logo.png', 'bg.png': 'bg.jpg', 'cozybg.png': 'cozybg.jpg', 'home.png': 'home.jpg'}
        filename = aliases.get(filename, filename)
        if filename not in ('index.html', 'app.js', 'app.css', 'logo.png', 'bg.jpg', 'cozybg.jpg', 'home.jpg'):
            raise web.HTTPNotFound()
        if filename == 'index.html':
            raise web.HTTPNotFound()
        if filename == 'app.js':
            content = (STATIC / filename).read_text(encoding='utf-8').replace('/knight/', panel + '/')
            content = content.replace('Check Replit → Account → Usage before more traffic is billed.', 'Check your VPS provider usage meter.')
            content = content.replace('Replit → Account → Usage is the real meter.', 'Transport overhead is included in these counters.')
            return web.Response(text=content, content_type='application/javascript')
        return web.FileResponse(STATIC / filename, headers={'Cache-Control': 'public, max-age=86400'})

    for path in ('/', panel, panel + '/'):
        app.router.add_get(path, panel_view)
    app.router.add_get(panel + '/login', login)
    app.router.add_post(panel + '/login', login)
    app.router.add_get(panel + '/logout', logout)
    app.router.add_get('/health', health)
    app.router.add_get('/healthz', readiness)
    app.router.add_get(panel + '/api/qr', qr)
    for prefix in ('/api/latest-video', panel + '/api/latest-video'):
        app.router.add_get(prefix, latest_video)
    app.router.add_get(panel + '/api/traffic', traffic_api)
    for suffix in ('reset', 'baseline'):
        app.router.add_post(panel + '/api/traffic/' + suffix, traffic_api)
    app.router.add_get(panel + '/{format:raw|base64|sub|clash|clash.yaml|sb|sb/raw|sb/base64|xray/raw|xray/base64|wg.conf|wireguard.conf}', subscription)
    for fmt in ('sub', 'base64', 'clash', 'sb', 'wg.conf'):
        app.router.add_get('/' + fmt, subscription)
    for prefix in ('/knight-assets/', '/assets/', panel + '/assets/'):
        app.router.add_get(prefix + '{file}', asset)
    return app
