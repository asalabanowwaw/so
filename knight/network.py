import asyncio
import logging
import ssl
import struct
import time
from contextlib import suppress
from urllib.parse import urlsplit

from .config import PATHS, GRPC, TROJAN_GRPC
from .h2proxy import serve_h2

log = logging.getLogger('knight.network')


def client_hello(data):
    """Read SNI and ALPN from one complete TLS ClientHello (across TLS records)."""
    try:
        handshake = bytearray()
        pos = 0
        while pos + 5 <= len(data):
            size = int.from_bytes(data[pos + 3:pos + 5], 'big')
            if data[pos] != 22 or pos + 5 + size > len(data):
                return None, []
            handshake.extend(data[pos + 5:pos + 5 + size])
            pos += 5 + size
            if len(handshake) >= 4 and len(handshake) >= 4 + int.from_bytes(handshake[1:4], 'big'):
                break
        if len(handshake) < 39 or handshake[0] != 1:
            return None, []
        offset = 4 + 2 + 32
        offset += 1 + handshake[offset]
        offset += 2 + int.from_bytes(handshake[offset:offset + 2], 'big')
        offset += 1 + handshake[offset]
        end = offset + 2 + int.from_bytes(handshake[offset:offset + 2], 'big')
        offset += 2
        sni, alpn = None, []
        while offset + 4 <= end:
            kind, length = struct.unpack('!HH', handshake[offset:offset + 4])
            value = handshake[offset + 4:offset + 4 + length]
            offset += 4 + length
            if kind == 0 and len(value) >= 5:
                name_len = int.from_bytes(value[3:5], 'big')
                sni = bytes(value[5:5 + name_len]).decode('ascii').lower()
            elif kind == 16:
                cursor = 2
                while cursor < len(value):
                    size = value[cursor]
                    alpn.append(bytes(value[cursor + 1:cursor + 1 + size]).decode('ascii'))
                    cursor += 1 + size
        return sni, alpn
    except (ValueError, IndexError, struct.error, UnicodeError):
        return None, []


async def read_hello(reader, initial):
    data = initial
    total = 0
    while len(data) < 131072:
        if len(data) < total + 5:
            data += await reader.readexactly(total + 5 - len(data))
        size = int.from_bytes(data[total + 3:total + 5], 'big')
        if size > 18432 or data[total] != 22:
            raise ValueError('Invalid TLS record')
        if len(data) < total + 5 + size:
            data += await reader.readexactly(total + 5 + size - len(data))
        total += 5 + size
        handshake = b''
        pos = 0
        while pos < total:
            length = int.from_bytes(data[pos + 3:pos + 5], 'big')
            handshake += data[pos + 5:pos + 5 + length]
            pos += 5 + length
        if len(handshake) >= 4 and len(handshake) >= 4 + int.from_bytes(handshake[1:4], 'big'):
            return data
    raise ValueError('TLS hello is too large')


class Router:
    def __init__(self, cfg, ports, traffic, engines):
        self.cfg, self.ports, self.traffic, self.engines = cfg, ports, traffic, engines
        self.servers = []
        self.connections = set()
        self.peers = {}
        self.udp = []

    def http_target(self, path):
        plain = urlsplit(path).path
        if plain.startswith('/' + GRPC + '/') and (self.cfg.enable['vlessGrpc'] or self.cfg.enable['vlessGrpcTls']):
            return self.ports['vlessGrpc'], 'VLESS-gRPC'
        if plain.startswith('/' + TROJAN_GRPC + '/') and self.cfg.enable['trojanGrpcTls']:
            return self.ports['trojanGrpc'], 'Trojan-gRPC'
        for key, canonical in PATHS.items():
            enabled = self.cfg.enable.get(key, False) or self.cfg.enable.get(key + 'Tls', False)
            if enabled and (plain.rstrip('/') == canonical or key == 'xhttp' and plain.startswith(canonical + '/')):
                return self.ports[key], {'vlessWs': 'VLESS-WS', 'vmessWs': 'VMess-WS',
                    'trojanWs': 'Trojan-WS', 'vlessHu': 'VLESS-HTTPUpgrade', 'vmessHu': 'VMess-HTTPUpgrade',
                    'trojanHu': 'Trojan-HTTPUpgrade', 'xhttp': 'VLESS-XHTTP', 'ssWs': 'Shadowsocks-WS'}[key]
        return None, None

    def h2_target(self, path):
        target, label = self.http_target(path)
        return (target, label) if target else (self.ports['web'], '__web__')

    async def pipe(self, reader, writer, target, label, initial=b'', original_peer=None):
        back_reader, back_writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', target), 5)
        peer_key = back_writer.get_extra_info('sockname')
        if original_peer:
            self.peers[peer_key] = original_peer
        if label:
            self.traffic.active[label] = self.traffic.active.get(label, 0) + 1

        async def copy(source, dest, direction):
            while data := await source.read(65536):
                dest.write(data)
                await dest.drain()
                if label:
                    self.traffic.add(label, **{direction: len(data)})
            if dest.can_write_eof():
                with suppress(OSError):
                    dest.write_eof()

        tasks = []
        try:
            if initial:
                back_writer.write(initial)
                await back_writer.drain()
                if label:
                    self.traffic.add(label, up=len(initial))
            tasks = [asyncio.create_task(copy(reader, back_writer, 'up')),
                     asyncio.create_task(copy(back_reader, writer, 'down'))]
            # Keep the opposite direction alive after a normal half-close.
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if any(t.exception() is not None for t in done):
                return
            if pending:
                await asyncio.wait_for(asyncio.gather(*pending), 120)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.peers.pop(peer_key, None)
            if label:
                self.traffic.active[label] = max(0, self.traffic.active.get(label, 1) - 1)
            back_writer.close()
            with suppress(OSError, ssl.SSLError):
                await back_writer.wait_closed()

    async def handle(self, reader, writer, decrypted=False):
        task = asyncio.current_task()
        self.connections.add(task)
        try:
            raw_peer = writer.get_extra_info('peername')
            peer = self.peers.get(raw_peer, raw_peer)
            tls_object = writer.get_extra_info('ssl_object')
            if decrypted and tls_object and tls_object.selected_alpn_protocol() == 'h2':
                await serve_h2(reader, writer, self.h2_target, self.traffic, peer=str(peer[0]), scheme='https')
                return
            initial = await asyncio.wait_for(reader.readexactly(1), 15)
            if not decrypted and initial == b'\x16':
                hello = await asyncio.wait_for(read_hello(reader, initial), 10)
                sni, alpn = client_hello(hello)
                if self.cfg.enable['reality'] and sni == self.cfg.reality_sni:
                    target, label = self.ports['reality'], 'REALITY'
                elif self.cfg.enable['shadowTls'] and sni == self.cfg.shadow_sni:
                    target, label = self.ports['shadowTls'], 'ShadowTLS-VLESS'
                else:
                    target, label = self.ports['tls'], None
                await self.pipe(reader, writer, target, label, hello, peer)
                return
            if initial == b'\x05' and self.cfg.enable['socks']:
                await self.pipe(reader, writer, self.ports['socks'], 'SOCKS5', initial)
                return
            if initial not in (b'G', b'P', b'H', b'O', b'D', b'C', b'T'):
                if self.cfg.enable['shadowsocks']:
                    await self.pipe(reader, writer, self.ports['shadowsocks'], 'Shadowsocks', initial)
                return
            initial += await asyncio.wait_for(reader.readexactly(7), 15)
            if not any(initial.startswith(verb) for verb in (b'GET ', b'POST ', b'HEAD ', b'OPTIONS ', b'DELETE ', b'CONNECT ', b'TRACE ', b'PATCH ', b'PUT ', b'PRI * HT')):
                if self.cfg.enable['shadowsocks']:
                    await self.pipe(reader, writer, self.ports['shadowsocks'], 'Shadowsocks', initial)
                return
            header = initial + await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 15)
            if header.startswith(b'PRI * HTTP/2.0\r\n'):
                # readuntil consumed only the first 18 bytes of the 24-byte preface.
                await serve_h2(reader, writer, self.h2_target, self.traffic, header, peer=str(peer[0]), scheme='http')
                return
            first = header.split(b'\r\n', 1)[0].decode('latin1').split(' ')
            if len(first) != 3:
                return
            method, path, version = first
            if (method == 'CONNECT' or path.startswith(('http://', 'https://'))) and self.cfg.enable['httpProxy']:
                await self.pipe(reader, writer, self.ports['httpProxy'], 'HTTP-Proxy', header)
                return
            target, label = self.http_target(path)
            if target:
                await self.pipe(reader, writer, target, label, header)
                return
            # The web app trusts only headers inserted here on its loopback connection.
            lines = [line for line in header.split(b'\r\n')[1:] if line and
                     not line.lower().startswith((b'x-bk-', b'x-forwarded-', b'connection:'))]
            address = str(peer[0]) if peer else 'unknown'
            lines += [b'X-BK-Client-IP: ' + address.encode('ascii'),
                      b'X-BK-Scheme: ' + (b'https' if decrypted else b'http'), b'Connection: close']
            rewritten = header.split(b'\r\n', 1)[0] + b'\r\n' + b'\r\n'.join(lines) + b'\r\n\r\n'
            await self.pipe(reader, writer, self.ports['web'], None, rewritten)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                ValueError, ssl.SSLError):
            pass
        finally:
            self.connections.discard(task)
            writer.close()
            with suppress(OSError, ssl.SSLError):
                await writer.wait_closed()

    async def start(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cfg.cert, self.cfg.key)
        context.set_alpn_protocols(['h2', 'http/1.1'])
        self.servers.append(await asyncio.start_server(lambda r, w: self.handle(r, w, True),
                            '127.0.0.1', self.ports['tls'], ssl=context, ssl_handshake_timeout=10, limit=65536))
        for public in (self.cfg.port, self.cfg.tls_port):
            self.servers.append(await asyncio.start_server(self.handle, self.cfg.bind, public, limit=65536))
        if self.cfg.enable['shadowsocks']:
            async def ss(reader, writer):
                task = asyncio.current_task()
                self.connections.add(task)
                try:
                    await self.pipe(reader, writer, self.ports['shadowsocks'], 'Shadowsocks')
                except (OSError, asyncio.TimeoutError):
                    pass
                finally:
                    self.connections.discard(task)
                    writer.close()
            self.servers.append(await asyncio.start_server(ss, self.cfg.bind, self.cfg.ss_port))
        for name, public in [('shadowsocks', self.cfg.ss_port), ('wireguard', self.cfg.wg_port),
                             ('hysteria2', self.cfg.hy_port), ('tuic', self.cfg.tuic_port)]:
            if self.cfg.enable[name]:
                relay = UDPRelay(self.ports[name], name, self.traffic)
                transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: relay,
                                            local_addr=(self.cfg.bind, public))
                self.udp.append((transport, relay))
        log.info('Public TCP listeners: %s:%s and :%s', self.cfg.bind, self.cfg.port, self.cfg.tls_port)

    async def close(self):
        for server in self.servers:
            server.close()
        for server in self.servers:
            await server.wait_closed()
        for task in list(self.connections):
            task.cancel()
        await asyncio.gather(*list(self.connections), return_exceptions=True)
        for transport, relay in self.udp:
            relay.close()
            transport.close()


class UDPRelay(asyncio.DatagramProtocol):
    def __init__(self, target, label, traffic):
        self.target, self.label, self.traffic = target, label, traffic
        self.clients = {}
        self.transport = None
        self.cleaner = None
        self.tasks = set()

    def connection_made(self, transport):
        self.transport = transport
        self.cleaner = asyncio.create_task(self.cleanup())

    def datagram_received(self, data, address):
        if address not in self.clients:
            if len(self.clients) >= 4096:
                return
            association = UDPAssociation(self, address)
            self.clients[address] = association
            task = asyncio.create_task(association.connect())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        self.clients[address].send(data)

    async def cleanup(self):
        while True:
            await asyncio.sleep(30)
            for address, association in list(self.clients.items()):
                if time.monotonic() - association.touched > 180:
                    association.close()
                    self.clients.pop(address, None)

    def close(self):
        if self.cleaner:
            self.cleaner.cancel()
        for task in self.tasks:
            task.cancel()
        for association in self.clients.values():
            association.close()


class UDPAssociation(asyncio.DatagramProtocol):
    def __init__(self, relay, address):
        self.relay, self.address = relay, address
        self.touched = time.monotonic()
        self.transport = None
        self.pending = []
        self.closed = False

    async def connect(self):
        try:
            transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: self,
                remote_addr=('127.0.0.1', self.relay.target))
            if self.closed:
                transport.close()
        except OSError:
            self.relay.clients.pop(self.address, None)

    def connection_made(self, transport):
        self.transport = transport
        for data in self.pending:
            transport.sendto(data)
        self.pending.clear()

    def send(self, data):
        self.touched = time.monotonic()
        if self.transport:
            self.transport.sendto(data)
        elif len(self.pending) < 32:
            self.pending.append(data)
        self.relay.traffic.add(self.relay.label, up=len(data))

    def datagram_received(self, data, _):
        self.touched = time.monotonic()
        self.relay.transport.sendto(data, self.address)
        self.relay.traffic.add(self.relay.label, down=len(data))

    def close(self):
        self.closed = True
        if self.transport:
            self.transport.close()
