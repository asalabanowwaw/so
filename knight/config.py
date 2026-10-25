import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PREFIX = '/@BlueKnight_Net--@BlueKnight_Net--@BlueKnight_Net--@BlueKnight_Net--'
PATHS = {k: PREFIX + v for k, v in {
    'vlessWs': 'ws', 'vmessWs': 'vmess', 'trojanWs': 'trojan',
    'vlessHu': 'httpupgrade', 'vmessHu': 'vmess-hu', 'trojanHu': 'trojan-hu',
    'xhttp': 'xhttp', 'ssWs': 'ss',
}.items()}
GRPC = PREFIX[1:] + 'grpc'
TROJAN_GRPC = GRPC + '-trojan'
SWITCHES = {
    'vlessWs': ('ENABLE_VLESS_WS', True), 'vlessWsTls': ('ENABLE_VLESS_WS_TLS', True),
    'vmessWs': ('ENABLE_VMESS_WS', True), 'vmessWsTls': ('ENABLE_VMESS_WS_TLS', True),
    'trojanWs': ('ENABLE_TROJAN_WS', True), 'trojanWsTls': ('ENABLE_TROJAN_WS_TLS', True),
    'vlessHu': ('ENABLE_HTTPUPGRADE', True), 'vmessHu': ('ENABLE_VMESS_HTTPUPGRADE', True),
    'trojanHu': ('ENABLE_TROJAN_HTTPUPGRADE', True), 'vlessGrpc': ('ENABLE_VLESS_GRPC', True),
    'vlessGrpcTls': ('ENABLE_VLESS_GRPC_TLS', True), 'trojanGrpcTls': ('ENABLE_TROJAN_GRPC_TLS', True),
    'xhttp': ('ENABLE_XHTTP', True), 'ssWs': ('ENABLE_SS_WS', True),
    'reality': ('ENABLE_REALITY', True), 'shadowTls': ('ENABLE_SHADOWTLS_VLESS', False),
    'shadowsocks': ('ENABLE_SS', True), 'wireguard': ('ENABLE_WIREGUARD', True),
    'hysteria2': ('ENABLE_HYSTERIA2', False), 'tuic': ('ENABLE_TUIC', False),
    'socks': ('ENABLE_SOCKS', False), 'httpProxy': ('ENABLE_HTTP_PROXY', False),
    'argo': ('ENABLE_ARGO', False),
}


def boolean(env, name, default=False):
    value = env.get(name)
    if value is None:
        return default
    if value.lower() not in ('true', 'false', '1', '0'):
        raise ValueError(f'{name} must be true/false or 1/0')
    return value.lower() in ('true', '1')


def port(env, name, default):
    value = int(env.get(name, default))
    if not 1 <= value <= 65535:
        raise ValueError(f'{name} must be 1–65535')
    return value


def host(value):
    value = value.strip()
    if not value:
        return ''
    parsed = urlsplit(value if '://' in value else '//' + value)
    result = parsed.hostname
    if not result or any(c in result for c in '\r\n /?#'):
        raise ValueError('Invalid DOMAIN / FORCE_HOST')
    return result


@dataclass
class Config:
    data: Path
    bind: str = '0.0.0.0'
    port: int = 8080
    tls_port: int = 443
    panel: str = 'knight'
    domain: str = ''
    force_host: str = ''
    public_base: str = ''
    ss_port: int = 8388
    wg_port: int = 51820
    hy_port: int = 8443
    tuic_port: int = 8444
    enable: dict = field(default_factory=dict)
    env: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, env=None):
        e = dict(os.environ if env is None else env)
        cfg = cls(data=Path(e.get('BK_DATA_DIR', 'bk-data')).resolve(),
                  bind=e.get('BIND_ADDRESS', '0.0.0.0'), port=port(e, 'PORT', e.get('SERVER_PORT', 8080)),
                  tls_port=port(e, 'TLS_PORT', 443), panel=e.get('PANEL_PATH', 'knight').strip('/'),
                  domain=host(e.get('DOMAIN', e.get('SB_DOMAIN', ''))),
                  force_host=host(e.get('FORCE_HOST', e.get('CFIP', ''))),
                  public_base=e.get('PUBLIC_BASE_URL', e.get('SUB_BASE_URL', '')).rstrip('/'),
                  ss_port=port(e, 'SS_PORT', 8388), wg_port=port(e, 'WG_PORT', 51820),
                  hy_port=port(e, 'HY2_PORT', 8443), tuic_port=port(e, 'TUIC_PORT', 8444), env=e)
        if not cfg.panel or not all(c.isalnum() or c in '-_' for c in cfg.panel):
            raise ValueError('PANEL_PATH may only contain letters, digits, hyphens and underscores')
        cfg.enable = {key: boolean(e, name, default) for key, (name, default) in SWITCHES.items()}
        if cfg.enable['shadowTls'] and cfg.enable['reality'] and cfg.shadow_sni == cfg.reality_sni:
            raise ValueError('SHADOWTLS_SNI must differ from REALITY_TARGET when both share a port')
        if cfg.port == cfg.tls_port:
            raise ValueError('PORT and TLS_PORT must differ (both listeners accept mixed TCP traffic)')
        udp = [cfg.ss_port] if cfg.enable['shadowsocks'] else []
        udp += [p for k, p in [('wireguard', cfg.wg_port), ('hysteria2', cfg.hy_port), ('tuic', cfg.tuic_port)] if cfg.enable[k]]
        if len(udp) != len(set(udp)):
            raise ValueError('Enabled UDP protocols require distinct public ports')
        if cfg.enable['shadowsocks'] and cfg.ss_port in (cfg.port, cfg.tls_port):
            raise ValueError('SS_PORT must differ from PORT and TLS_PORT')
        if cfg.public_base:
            u = urlsplit(cfg.public_base)
            if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.query or u.fragment or u.path not in ('', '/'):
                raise ValueError('PUBLIC_BASE_URL must be an HTTP(S) origin without a path')
        for key, default in [('WG_SERVER_IP', '10.66.66.1/24'), ('WG_CLIENT_IP', '10.66.66.2/32')]:
            ipaddress.ip_interface(e.get(key, default))
        return cfg

    @property
    def reality_sni(self):
        return self.env.get('REALITY_TARGET', 'www.google.com')

    @property
    def shadow_sni(self):
        return self.env.get('SHADOWTLS_SNI', 'www.apple.com')

    @property
    def cert(self):
        return Path(self.env.get('TLS_CERT', str(self.data / 'cert/cert.pem'))).resolve()

    @property
    def key(self):
        return Path(self.env.get('TLS_KEY', str(self.data / 'cert/key.pem'))).resolve()

    def advertised_host(self, state):
        return self.force_host or self.domain or state.get('publicHost') or '127.0.0.1'
