import asyncio
import base64
import json
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from knight.config import Config, PATHS
from knight.engines import allocate_ports, build_singbox, build_xray
from knight.links import Links
from knight.network import Router, UDPRelay, client_hello
from knight.storage import Auth, ensure_certificate, initialize_state, read_json
from knight.traffic import Traffic
from knight.web import make_app


class Fixture:
    def setup_fixture(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = Config.load({'BK_DATA_DIR': self.temp.name, 'DOMAIN': 'gate.example.com',
                                'PANEL_PASSWORD': 'test-password-123', 'PANEL_PATH': 'custom'})
        self.state = initialize_state(self.cfg)
        self.auth = Auth(self.cfg)
        self.traffic = Traffic(self.cfg)
        self.supervisor = Mock()
        self.supervisor.status.return_value = {'singbox': True, 'xray': True, 'argo': False}
        self.supervisor.argo_domain = ''


class CoreTests(Fixture, unittest.TestCase):
    def setUp(self):
        self.setup_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def test_state_persists_keys_and_identities(self):
        second = initialize_state(self.cfg)
        self.assertEqual(self.state, second)
        self.assertEqual(self.auth.data['subToken'], Auth(self.cfg).data['subToken'])

    def test_signed_sessions_and_passwords(self):
        self.assertTrue(self.auth.verify('test-password-123'))
        self.assertFalse(self.auth.verify('incorrect'))
        value = self.auth.session()
        self.assertTrue(self.auth.valid(value))
        self.assertFalse(self.auth.valid(value + 'x'))
        self.auth.set_password('new-password')
        self.assertFalse(self.auth.valid(value))

    def test_config_rejects_conflicting_ports_and_sni(self):
        for env in ({'PORT': '443'}, {'ENABLE_SHADOWTLS_VLESS': 'true', 'SHADOWTLS_SNI': 'www.google.com'},
                    {'TLS_PORT': '70000'}, {'ENABLE_TUIC': 'true', 'TUIC_PORT': '51820'}):
            with self.assertRaises(ValueError):
                Config.load(env)

    def test_engine_configs_cover_protocols(self):
        self.cfg.enable.update(shadowTls=True, hysteria2=True, tuic=True, socks=True, httpProxy=True)
        ensure_certificate(self.cfg)
        ports = allocate_ports()
        cfg = build_singbox(self.cfg, self.state, ports)
        types = {v['type'] for v in cfg['inbounds']}
        self.assertTrue({'vless', 'vmess', 'trojan', 'shadowtls', 'hysteria2', 'tuic', 'http', 'socks', 'shadowsocks'} <= types)
        self.assertEqual(cfg['endpoints'][0]['type'], 'wireguard')
        self.assertEqual(len(build_xray(self.cfg, self.state, ports)['inbounds']), 2)

    def test_no_dead_engine_links(self):
        self.assertEqual(Links(self.cfg, self.state, {'singbox': False, 'xray': False}).nodes, [])

    def test_client_exports_and_shadow_chain(self):
        self.cfg.enable['shadowTls'] = True
        links = Links(self.cfg, self.state, self.supervisor.status())
        tags = {n['name'] for n in links.nodes}
        self.assertEqual(len(tags), len(links.nodes))
        config = links.singbox()
        all_tags = {x['tag'] for x in config['outbounds']}
        chain = next(x for x in config['outbounds'] if x.get('detour'))
        self.assertIn(chain['detour'], all_tags)
        self.assertEqual(chain['type'], 'vless')
        self.assertIn('10.66.66.2/32', links.wireguard_conf())
        self.assertNotIn('PrivateKey = ' + self.state['wireguardPrivateKey'], links.wireguard_conf())

    def test_traffic_baseline_rollover_and_persistence(self):
        self.traffic.add('VLESS-WS', up=120, down=80)
        self.traffic.baseline(2)
        self.assertEqual(self.traffic.snapshot()['month']['used'], 2 * 1024 ** 3)
        restored = Traffic(self.cfg)
        self.assertEqual(restored.snapshot()['month']['used'], 2 * 1024 ** 3)
        restored.state['month']['key'] = '2000-01'
        self.assertEqual(restored.snapshot()['month']['used'], 0)
        restored.reset()
        self.assertEqual(restored.snapshot()['allTime']['total'], 0)

    def test_tls_client_hello_sni_and_alpn(self):
        context = ssl.create_default_context()
        context.set_alpn_protocols(['h2', 'http/1.1'])
        outgoing = ssl.MemoryBIO()
        client = context.wrap_bio(ssl.MemoryBIO(), outgoing, server_side=False, server_hostname='gate.example.com')
        try:
            client.do_handshake()
        except ssl.SSLWantReadError:
            pass
        data = outgoing.read()
        self.assertEqual(client_hello(data), ('gate.example.com', ['h2', 'http/1.1']))
        self.assertEqual(client_hello(b'broken'), (None, []))


class WebTests(Fixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_fixture()
        self.client = TestClient(TestServer(make_app(self.cfg, self.state, self.auth, self.traffic, self.supervisor)),
                                 cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def login(self):
        response = await self.client.post('/custom/login', data={'password': 'test-password-123'}, allow_redirects=False)
        self.assertEqual(response.status, 302)

    async def test_login_and_custom_panel_assets(self):
        response = await self.client.get('/custom', allow_redirects=False)
        self.assertEqual(response.status, 302)
        await self.login()
        response = await self.client.get('/custom')
        self.assertEqual(response.status, 200)
        self.assertIn('/custom/wg.conf', await response.text())
        response = await self.client.get('/knight-assets/app.js')
        self.assertIn('/custom/api/qr', await response.text())

    async def test_authenticated_exports_and_token(self):
        self.assertEqual((await self.client.get('/custom/raw')).status, 401)
        token = self.auth.data['subToken']
        response = await self.client.get('/custom/raw', params={'token': token})
        raw = await response.text()
        self.assertEqual(response.status, 200)
        response = await self.client.get('/sub', params={'token': token})
        self.assertEqual(base64.b64decode(await response.text()).decode(), raw)
        self.assertEqual((await self.client.get('/custom/api/traffic', params={'token': token})).status, 401)
        await self.login()
        for path in ('clash', 'sb/raw', 'sb/base64', 'xray/raw', 'xray/base64', 'wg.conf'):
            self.assertEqual((await self.client.get('/custom/' + path)).status, 200, path)

    async def test_csrf_and_invalid_baseline(self):
        await self.login()
        url = '/custom/api/traffic/baseline'
        self.assertEqual((await self.client.post(url, json={'gb': 10})).status, 403)
        for bad in (float('nan'), -1, 'oops'):
            response = await self.client.post(url, json={'gb': bad}, headers={'X-BK-Req': '1'})
            self.assertEqual(response.status, 400)
        response = await self.client.post(url, json={'gb': 3}, headers={'X-BK-Req': '1'})
        self.assertEqual((await response.json())['month']['used'], 3 * 1024 ** 3)
        response = await self.client.post('/custom/login', data={'password': 'test-password-123'}, headers={'Origin': 'https://attacker.example'})
        self.assertEqual(response.status, 403)

    async def test_local_qr_and_readiness(self):
        self.assertEqual((await self.client.get('/custom/api/qr?data=test')).status, 401)
        await self.login()
        response = await self.client.get('/custom/api/qr?data=vless://test')
        self.assertEqual(response.status, 200)
        self.assertIn('<svg', await response.text())
        self.supervisor.status.return_value['xray'] = False
        self.assertEqual((await self.client.get('/healthz')).status, 503)
        health = await (await self.client.get('/health')).json()
        self.assertFalse(any(n['type'].startswith('VLESS-XHTTP') for n in health['nodes']))

    async def test_rate_limiting(self):
        for _ in range(8):
            response = await self.client.post('/custom/login', data={'password': 'wrong'}, allow_redirects=False)
            self.assertEqual(response.status, 401)
        response = await self.client.post('/custom/login', data={'password': 'wrong'})
        self.assertEqual(response.status, 429)

    async def test_tunnel_origin_uses_secure_cookie(self):
        self.supervisor.argo_domain = 'example.trycloudflare.com'
        response = await self.client.post('/custom/login', data={'password': 'test-password-123'},
            headers={'Host': 'example.trycloudflare.com', 'Origin': 'https://example.trycloudflare.com'},
            allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertTrue(response.cookies['bk_session']['secure'])


class RoutingTests(Fixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_fixture()
        self.servers = []

    async def asyncTearDown(self):
        for server in self.servers:
            server.close()
            await server.wait_closed()
        self.temp.cleanup()

    async def test_real_tcp_half_close_and_meter(self):
        async def echo(reader, writer):
            data = await reader.read()
            writer.write(data.upper())
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(echo, '127.0.0.1', 0)
        self.servers.append(server)
        target = server.sockets[0].getsockname()[1]
        router = Router(self.cfg, {}, self.traffic, self.supervisor)
        async def proxy(reader, writer):
            try:
                await router.pipe(reader, writer, target, 'test')
            finally:
                writer.close()
        front = await asyncio.start_server(proxy, '127.0.0.1', 0)
        self.servers.append(front)
        reader, writer = await asyncio.open_connection('127.0.0.1', front.sockets[0].getsockname()[1])
        writer.write(b'blue knight')
        await writer.drain()
        writer.write_eof()
        self.assertEqual(await asyncio.wait_for(reader.read(), 5), b'BLUE KNIGHT')
        writer.close()
        await writer.wait_closed()
        self.assertEqual(self.traffic.snapshot()['allTime']['total'], 22)

    async def test_udp_associations_and_meter(self):
        class Echo(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport
            def datagram_received(self, data, address):
                self.transport.sendto(data.upper(), address)
        loop = asyncio.get_running_loop()
        target, _ = await loop.create_datagram_endpoint(Echo, local_addr=('127.0.0.1', 0))
        relay = UDPRelay(target.get_extra_info('sockname')[1], 'UDP', self.traffic)
        front, _ = await loop.create_datagram_endpoint(lambda: relay, local_addr=('127.0.0.1', 0))
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            await loop.sock_sendto(sock, b'knight', front.get_extra_info('sockname'))
            data, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 1024), 5)
            self.assertEqual(data, b'KNIGHT')
            self.assertEqual(self.traffic.snapshot()['allTime']['total'], 12)
        finally:
            sock.close()
            relay.close()
            front.close()
            target.close()
            await asyncio.sleep(0)


if __name__ == '__main__':
    unittest.main()
