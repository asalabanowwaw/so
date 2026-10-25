"""Native core configuration, pinned downloads and supervised processes."""
import asyncio
import hashlib
import io
import logging
import os
import platform
import re
import socket
import tarfile
import time
import secrets
import urllib.request
import zipfile
from pathlib import Path

from .config import PATHS, GRPC, TROJAN_GRPC
from .storage import write_json

log = logging.getLogger('knight.engines')
SING_VERSION = '1.11.15'
XRAY_VERSION = '25.6.8'
CLOUDFLARED_VERSION = '2026.10.0'


def free_port(udp=False):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def allocate_ports():
    ports = {}
    for name in (*PATHS, 'vlessGrpc', 'trojanGrpc', 'reality', 'shadowTls', 'shadowsocks',
                 'socks', 'httpProxy', 'hysteria2', 'tuic', 'wireguard', 'web', 'tls'):
        candidate = free_port(name in ('hysteria2', 'tuic', 'wireguard'))
        while candidate in ports.values():
            candidate = free_port()
        ports[name] = candidate
    return ports


def binary_path(cfg, name):
    override = cfg.env.get({'singbox': 'SINGBOX_BIN', 'xray': 'XRAY_BIN', 'argo': 'CLOUDFLARED_BIN'}[name])
    if override:
        return Path(override).resolve()
    binary = {'singbox': 'sing-box', 'xray': 'xray', 'argo': 'cloudflared'}[name]
    filename = binary + ('.exe' if os.name == 'nt' else '')
    preinstalled = Path('/opt/blue-knight/bin') / filename
    return preinstalled if preinstalled.exists() else cfg.data / 'bin' / filename


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'BlueKnight-Python/1.0'})
    with urllib.request.urlopen(request, timeout=90) as response:
        content = response.read(150 * 1024 * 1024 + 1)
    if len(content) > 150 * 1024 * 1024:
        raise RuntimeError('Engine download exceeded size limit')
    return content


def install_binary(cfg, name):
    dest = binary_path(cfg, name)
    if dest.exists():
        return dest
    arch = platform.machine().lower()
    if arch not in ('amd64', 'x86_64', 'arm64', 'aarch64'):
        raise RuntimeError(f'Unsupported architecture: {arch}; provide a compatible *_BIN executable')
    arm = arch in ('arm64', 'aarch64')
    system = platform.system().lower()
    if system not in ('linux', 'windows', 'darwin'):
        raise RuntimeError(f'Unsupported system: {system}')
    if name == 'singbox':
        version = cfg.env.get('SINGBOX_VERSION', SING_VERSION).lstrip('v')
        extension = 'zip' if system == 'windows' else 'tar.gz'
        filename = f'sing-box-{version}-{system}-{"arm64" if arm else "amd64"}.{extension}'
        url = f'https://github.com/SagerNet/sing-box/releases/download/v{version}/{filename}'
    elif name == 'xray':
        version = cfg.env.get('XRAY_VERSION', XRAY_VERSION).lstrip('v')
        cpu = ('arm64-v8a' if arm else '64') if system == 'linux' else ('arm64' if arm else '64')
        filename = f'Xray-{system}-{cpu}.zip'
        url = f'https://github.com/XTLS/Xray-core/releases/download/v{version}/{filename}'
    else:
        version = cfg.env.get('CLOUDFLARED_VERSION', CLOUDFLARED_VERSION)
        suffix = '.exe' if system == 'windows' else ('.tgz' if system == 'darwin' else '')
        url = f'https://github.com/cloudflare/cloudflared/releases/download/{version}/cloudflared-{system}-{"arm64" if arm else "amd64"}{suffix}'
    log.info('Installing %s from its official release', name)
    content = fetch(url)
    expected = cfg.env.get({'singbox': 'SINGBOX_SHA256', 'xray': 'XRAY_SHA256', 'argo': 'CLOUDFLARED_SHA256'}[name])
    if expected and hashlib.sha256(content).hexdigest().lower() != expected.lower():
        raise RuntimeError(f'{name}: SHA256 mismatch')
    wanted = dest.name
    if url.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            member = next(n for n in archive.namelist() if Path(n).name == wanted)
            content = archive.read(member)
    elif url.endswith(('.tar.gz', '.tgz')):
        with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
            member = next(n for n in archive.getmembers() if Path(n.name).name == wanted and n.isfile())
            content = archive.extractfile(member).read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix('.download')
    temp.write_bytes(content)
    temp.chmod(0o755)
    os.replace(temp, dest)
    return dest


def build_singbox(cfg, state, ports):
    inbound = []
    enabled = cfg.enable
    uid = state['uuid']

    def add(key, protocol, transport=None):
        item = {'type': protocol, 'tag': key, 'listen': '127.0.0.1', 'listen_port': ports[key]}
        item['users'] = ([{'uuid': uid, 'alterId': 0}] if protocol == 'vmess' else
                         [{'password': uid}] if protocol == 'trojan' else [{'uuid': uid}])
        if transport:
            item['transport'] = transport
        inbound.append(item)
        return item

    for key, protocol in [('vlessWs', 'vless'), ('vmessWs', 'vmess'), ('trojanWs', 'trojan')]:
        if enabled[key] or enabled[key + 'Tls']:
            transport = {'type': 'ws', 'path': PATHS[key]}
            if protocol != 'trojan':
                transport.update(max_early_data=2560, early_data_header_name='Sec-WebSocket-Protocol')
            add(key, protocol, transport)
    for key, protocol in [('vlessHu', 'vless'), ('vmessHu', 'vmess'), ('trojanHu', 'trojan')]:
        if enabled[key]:
            add(key, protocol, {'type': 'httpupgrade', 'path': PATHS[key]})
    if enabled['vlessGrpc'] or enabled['vlessGrpcTls']:
        add('vlessGrpc', 'vless', {'type': 'grpc', 'service_name': GRPC})
    if enabled['trojanGrpcTls']:
        add('trojanGrpc', 'trojan', {'type': 'grpc', 'service_name': TROJAN_GRPC})
    if enabled['reality']:
        item = add('reality', 'vless')
        item['users'][0]['flow'] = 'xtls-rprx-vision'
        item['tls'] = {'enabled': True, 'server_name': cfg.reality_sni,
                       'reality': {'enabled': True, 'handshake': {'server': cfg.reality_sni,
                                    'server_port': int(cfg.env.get('REALITY_TARGET_PORT', 443))},
                                   'private_key': state['realityPrivateKey'], 'short_id': [state['realityShortId']]}}
    if enabled['shadowTls']:
        inbound += [
            {'type': 'shadowtls', 'tag': 'shadowTls', 'listen': '127.0.0.1', 'listen_port': ports['shadowTls'],
             'version': 3, 'users': [{'name': 'knight', 'password': state['shadowTlsPassword']}],
             'handshake': {'server': cfg.shadow_sni, 'server_port': 443}, 'strict_mode': True, 'detour': 'shadow-vless'},
            {'type': 'vless', 'tag': 'shadow-vless', 'users': [{'uuid': uid}]}]
    if enabled['shadowsocks']:
        inbound.append({'type': 'shadowsocks', 'tag': 'shadowsocks', 'listen': '127.0.0.1',
                        'listen_port': ports['shadowsocks'], 'method': cfg.env.get('SS_METHOD', 'aes-256-gcm'),
                        'password': state['shadowsocksPassword']})
    for key, proto, prefix in [('socks', 'socks', 'SOCKS'), ('httpProxy', 'http', 'HTTP_PROXY')]:
        if enabled[key]:
            inbound.append({'type': proto, 'tag': key, 'listen': '127.0.0.1', 'listen_port': ports[key],
                            'users': [{'username': cfg.env.get(prefix + '_USER') or 'knight',
                                       'password': cfg.env.get(prefix + '_PASSWORD') or uid}]})
    tls = {'enabled': True, 'certificate_path': str(cfg.cert), 'key_path': str(cfg.key)}
    if enabled['hysteria2']:
        inbound.append({'type': 'hysteria2', 'tag': 'hysteria2', 'listen': '127.0.0.1', 'listen_port': ports['hysteria2'],
                        'users': [{'password': uid}], 'tls': {**tls, 'alpn': ['h3']},
                        'obfs': {'type': 'salamander', 'password': state['hy2ObfsPassword']},
                        'masquerade': cfg.env.get('MASS_PROXY_URL', 'https://www.gstatic.com')})
    if enabled['tuic']:
        inbound.append({'type': 'tuic', 'tag': 'tuic', 'listen': '127.0.0.1', 'listen_port': ports['tuic'],
                        'users': [{'uuid': uid, 'password': uid}], 'congestion_control': cfg.env.get('TUIC_CC', 'bbr'),
                        'tls': {**tls, 'alpn': ['h3']}})
    config = {'log': {'level': 'info', 'timestamp': True}, 'inbounds': inbound,
              'outbounds': [{'type': 'direct', 'tag': 'direct'}], 'route': {'final': 'direct'}}
    if enabled['wireguard']:
        config['endpoints'] = [{'type': 'wireguard', 'tag': 'wireguard', 'system': False, 'name': 'bk-wg0',
                                'mtu': int(cfg.env.get('WG_MTU', 1420)),
                                'address': [cfg.env.get('WG_SERVER_IP', '10.66.66.1/24')],
                                'private_key': state['wireguardPrivateKey'], 'listen_port': ports['wireguard'],
                                'peers': [{'public_key': state['wireguardClientPublicKey'],
                                           'allowed_ips': [cfg.env.get('WG_CLIENT_IP', '10.66.66.2/32')]}]}]
    return config


def build_xray(cfg, state, ports):
    inbound = []
    if cfg.enable['xhttp']:
        inbound.append({'tag': 'xhttp', 'listen': '127.0.0.1', 'port': ports['xhttp'], 'protocol': 'vless',
                        'settings': {'clients': [{'id': state['uuid']}], 'decryption': 'none'},
                        'streamSettings': {'network': 'xhttp', 'security': 'none',
                                           'xhttpSettings': {'path': PATHS['xhttp'], 'mode': 'auto'}}})
    if cfg.enable['ssWs']:
        inbound.append({'tag': 'ssWs', 'listen': '127.0.0.1', 'port': ports['ssWs'], 'protocol': 'shadowsocks',
                        'settings': {'method': cfg.env.get('SS_METHOD', 'aes-256-gcm'),
                                     'password': state['shadowsocksPassword'], 'network': 'tcp'},
                        'streamSettings': {'network': 'ws', 'security': 'none', 'wsSettings': {'path': PATHS['ssWs']}}})
    return {'log': {'loglevel': cfg.env.get('XRAY_LOG_LEVEL', 'warning')}, 'inbounds': inbound,
            'outbounds': [{'protocol': 'freedom', 'tag': 'direct'}]}


class Supervisor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.processes = {}
        self.tasks = []
        self.stopping = False
        self.argo_domain = cfg.env.get('ARGO_DOMAIN', '')
        self.history = {}

    def status(self):
        return {name: name in self.processes and self.processes[name].returncode is None
                for name in ('singbox', 'xray', 'argo')}

    async def check(self, binary, args):
        process = await asyncio.create_subprocess_exec(str(binary), *args,
                         stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 30)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f'Engine config check timed out: {binary.name}') from None
        if process.returncode:
            raise RuntimeError(f'{binary.name} rejected its configuration:\n{output.decode(errors="replace")[-5000:]}')

    async def prepare(self, state, ports, install=True, validate_only=False):
        jobs = [('singbox', build_singbox(self.cfg, state, ports), 'sing-box.json')]
        if self.cfg.enable['xhttp'] or self.cfg.enable['ssWs']:
            jobs.append(('xray', build_xray(self.cfg, state, ports), 'xray.json'))
        self.commands = {}
        for name, config, filename in jobs:
            binary = await asyncio.to_thread(install_binary, self.cfg, name) if install else binary_path(self.cfg, name)
            if not binary.exists():
                raise RuntimeError(f'Missing engine: {binary}; run python streamlit_app.py --install-engines')
            path = self.cfg.data / (('check-' + secrets.token_hex(8) + '-') + filename if validate_only else filename)
            write_json(path, config)
            try:
                await self.check(binary, ['check', '-c', str(path)] if name == 'singbox' else ['run', '-test', '-c', str(path)])
            finally:
                if validate_only:
                    path.unlink(missing_ok=True)
            self.commands[name] = [str(binary), 'run', '-c', str(path)]
        if self.cfg.enable['argo']:
            binary = await asyncio.to_thread(install_binary, self.cfg, 'argo') if install else binary_path(self.cfg, 'argo')
            if not binary.exists():
                raise RuntimeError('cloudflared binary is missing')
            command = [str(binary), 'tunnel', '--no-autoupdate']
            token = self.cfg.env.get('ARGO_AUTH', '')
            if token:
                # Pass named tunnel token through the child environment, never argv/logs.
                command += ['run']
                if not self.argo_domain:
                    raise ValueError('ARGO_DOMAIN is required for a named tunnel')
            else:
                command += ['--url', f'http://127.0.0.1:{self.cfg.port}']
            self.commands['argo'] = command

    async def start(self):
        for name, command in self.commands.items():
            task = asyncio.create_task(self.watch(name, command), name='engine-' + name)
            self.tasks.append(task)
        # Confirm engines did not exit immediately before advertising any node.
        await asyncio.sleep(0.8)
        for name in self.commands:
            if not self.status()[name]:
                raise RuntimeError(f'{name} failed to start; inspect {self.cfg.data / (name + ".log")}')

    async def watch(self, name, command):
        attempt = 0
        while not self.stopping and attempt < 20:
            logfile = self.cfg.data / (name + '.log')
            if logfile.exists() and logfile.stat().st_size > 5 * 1024 * 1024:
                logfile.replace(logfile.with_suffix('.log.1'))
            env = dict(os.environ)
            if name == 'argo' and self.cfg.env.get('ARGO_AUTH'):
                env['TUNNEL_TOKEN'] = self.cfg.env['ARGO_AUTH']
            started = time.monotonic()
            try:
                process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env)
                self.processes[name] = process
                log.info('%s started (pid %s)', name, process.pid)
                handle = logfile.open('ab')
                try:
                    async for line in process.stdout:
                        if handle.tell() + len(line) > 5 * 1024 * 1024:
                            handle.close()
                            logfile.replace(logfile.with_suffix('.log.1'))
                            handle = logfile.open('ab')
                        handle.write(line)
                        handle.flush()
                        if name == 'argo':
                            match = re.search(rb'https://([a-z0-9-]+\.trycloudflare\.com)', line)
                            if match:
                                self.argo_domain = match[1].decode()
                finally:
                    handle.close()
                await process.wait()
                self.history[name] = {'exitCode': process.returncode, 'restarts': attempt}
            except (OSError, asyncio.CancelledError):
                if self.stopping:
                    break
                log.exception('%s process failed', name)
            if self.stopping:
                break
            attempt = 0 if time.monotonic() - started > 300 else attempt + 1
            log.error('%s exited; restart attempt %s/20', name, attempt)
            await asyncio.sleep(min(30, 1 + attempt))

    async def close(self):
        self.stopping = True
        for process in self.processes.values():
            if process.returncode is None:
                process.terminate()
        for process in self.processes.values():
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), 8)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
