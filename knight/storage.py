import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, x25519
from cryptography.x509.oid import NameOID


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {} if default is None else default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    path.chmod(0o600)


def keypair(urlsafe=False):
    private = x25519.X25519PrivateKey.generate()
    encode = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    secret = encode(private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                         serialization.NoEncryption())).decode()
    public = encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    return (secret.rstrip('='), public.rstrip('=')) if urlsafe else (secret, public)


def initialize_state(cfg):
    state = read_json(cfg.data / 'state.json')
    raw = cfg.env.get('UUID', cfg.env.get('SB_UUID'))
    if raw:
        try:
            state['uuid'] = str(uuid.UUID(raw))
        except ValueError:
            state['uuid'] = str(uuid.UUID(bytes=hashlib.sha256(raw.encode()).digest()[:16], version=4))
    state.setdefault('uuid', str(uuid.uuid4()))
    uuid.UUID(state['uuid'])
    for key, env, size in [('shadowTlsPassword', 'SHADOWTLS_PASSWORD', 24),
                            ('shadowsocksPassword', 'SS_PASSWORD', 24),
                            ('hy2ObfsPassword', 'HY2_OBFS_PASSWORD', 16)]:
        state[key] = cfg.env.get(env) or state.get(key) or secrets.token_urlsafe(size)
    method = cfg.env.get('SS_METHOD', 'aes-256-gcm')
    if method.startswith('2022-'):
        size = 16 if method == '2022-blake3-aes-128-gcm' else 32
        try:
            valid = len(base64.b64decode(state['shadowsocksPassword'], validate=True)) == size
        except ValueError:
            valid = False
        if not valid:
            if cfg.env.get('SS_PASSWORD'):
                raise ValueError(f'SS_PASSWORD must be a base64 {size}-byte key for {method}')
            state['shadowsocksPassword'] = base64.b64encode(secrets.token_bytes(size)).decode()
    for private, public, urlsafe in [('realityPrivateKey', 'realityPublicKey', True),
                                     ('wireguardPrivateKey', 'wireguardPublicKey', False),
                                     ('wireguardClientPrivateKey', 'wireguardClientPublicKey', False)]:
        if not state.get(private):
            state[private], state[public] = keypair(urlsafe)
        else:
            raw_key = base64.urlsafe_b64decode(state[private] + '=' * (-len(state[private]) % 4))
            pub = x25519.X25519PrivateKey.from_private_bytes(raw_key).public_key()
            encoded = (base64.urlsafe_b64encode if urlsafe else base64.b64encode)(
                pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
            state[public] = encoded.rstrip('=') if urlsafe else encoded
    state['realityShortId'] = cfg.env.get('REALITY_SHORT_ID') or state.get('realityShortId') or secrets.token_hex(4)
    sid = state['realityShortId']
    if len(sid) > 16 or len(sid) % 2 or any(c not in '0123456789abcdefABCDEF' for c in sid):
        raise ValueError('REALITY_SHORT_ID must be an even number of hexadecimal characters, at most 16')
    write_json(cfg.data / 'state.json', state)
    return state


def ensure_certificate(cfg):
    if cfg.cert.exists() and cfg.key.exists():
        return
    if cfg.env.get('TLS_CERT') or cfg.env.get('TLS_KEY'):
        raise ValueError('TLS_CERT and TLS_KEY must both point to existing PEM files')
    name = cfg.domain or 'localhost'
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    import ipaddress
    try:
        san = x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        san = x509.DNSName(name)
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365)).add_extension(x509.SubjectAlternativeName([san]), False)
            .sign(key, hashes.SHA256()))
    cfg.cert.parent.mkdir(parents=True, exist_ok=True)
    cfg.key.parent.mkdir(parents=True, exist_ok=True)
    cfg.key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cfg.key.chmod(0o600)
    cfg.cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


class Auth:
    def __init__(self, cfg):
        self.path = cfg.data / 'auth.json'
        self.data = read_json(self.path)
        self.failures = {}
        if cfg.env.get('RESET_PANEL_PASSWORD') == 'true':
            self.data = {}
        self.data.setdefault('secret', secrets.token_hex(32))
        self.data['subToken'] = cfg.env.get('SUB_TOKEN') or self.data.get('subToken') or secrets.token_urlsafe(32)
        password = cfg.env.get('PANEL_PASSWORD')
        if password:
            if len(password) < 8:
                raise ValueError('PANEL_PASSWORD must contain at least 8 characters')
            if not self.verify(password):
                self.set_password(password)
        write_json(self.path, self.data)

    def set_password(self, password):
        salt = secrets.token_hex(16)
        self.data.update(salt=salt, hash=hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex(),
                         secret=secrets.token_hex(32))
        write_json(self.path, self.data)

    def verify(self, password):
        if not self.data.get('hash') or len(password) > 1024:
            return False
        digest = hashlib.scrypt(password.encode(), salt=self.data['salt'].encode(), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(digest, self.data['hash'])

    def session(self):
        expiry = str(int(time.time() * 1000) + 30 * 86400000)
        signature = hmac.new(self.data['secret'].encode(), expiry.encode(), hashlib.sha256).hexdigest()
        return expiry + '.' + signature

    def valid(self, value):
        try:
            expiry, signature = value.split('.')
            expected = hmac.new(self.data['secret'].encode(), expiry.encode(), hashlib.sha256).hexdigest()
            return bool(self.data.get('hash') and int(expiry) > time.time() * 1000 and hmac.compare_digest(signature, expected))
        except (ValueError, AttributeError):
            return False

    def blocked(self, ip):
        now = time.monotonic()
        self.failures = {k: v for k, v in self.failures.items() if now - v[1] < 900}
        return self.failures.get(ip, (0, now))[0] >= 8

    def failed(self, ip):
        if len(self.failures) >= 10000:
            self.failures.pop(next(iter(self.failures)))
        count, since = self.failures.get(ip, (0, time.monotonic()))
        self.failures[ip] = (count + 1, since)
