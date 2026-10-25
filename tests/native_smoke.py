"""Opt-in end-to-end tests using real sing-box/Xray binaries, no external target traffic.

python tests/native_smoke.py --singbox-bin PATH --xray-bin PATH
"""
import argparse
import hashlib
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlencode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from knight.config import Config
from knight.engines import free_port
from knight.links import Links
from knight.storage import read_json
import h2.config
import h2.connection
import h2.events


class Target(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'B' * (2 * 1024 * 1024) if self.path == '/bulk' else b'Blue Knight native proxy test passed'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = self.rfile.read(int(self.headers['Content-Length']))
        body = hashlib.sha256(data).hexdigest().encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def terminate(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def request_through_proxy(port, target_port, target_host='127.0.0.1', bulk=False):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=6)
    try:
        connection.request('GET', f'http://{target_host}:{target_port}/' + ('bulk' if bulk else 'native-test'))
        response = connection.getresponse()
        body = response.read()
        expected = b'B' * (2 * 1024 * 1024) if bulk else b'Blue Knight native proxy test passed'
        if response.status != 200 or body != expected:
            raise RuntimeError(f'Unexpected response: HTTP {response.status}: {body[:100]!r}')
        if bulk:
            payload = b'U' * (2 * 1024 * 1024)
            connection.close()
            connection.connect()
            connection.request('POST', f'http://{target_host}:{target_port}/echo', body=payload)
            response = connection.getresponse()
            if response.status != 200 or response.read() != hashlib.sha256(payload).hexdigest().encode():
                raise RuntimeError('Large upload content mismatch')
    finally:
        connection.close()


def h2_request(port, path, method='GET', body=b'', headers=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Generated test certificate only.
    context.set_alpn_protocols(['h2'])
    with context.wrap_socket(socket.create_connection(('127.0.0.1', port), timeout=10), server_hostname='localhost') as sock:
        assert sock.selected_alpn_protocol() == 'h2'
        conn = h2.connection.H2Connection(h2.config.H2Configuration(header_encoding='utf-8'))
        conn.initiate_connection()
        conn.send_headers(1, [(':method', method), (':scheme', 'https'), (':authority', f'127.0.0.1:{port}'),
                              (':path', path), *(headers or [])], end_stream=not body)
        if body:
            conn.send_data(1, body, end_stream=True)
        sock.sendall(conn.data_to_send())
        response_headers, result = {}, bytearray()
        while data := sock.recv(65536):
            complete = False
            for event in conn.receive_data(data):
                if isinstance(event, h2.events.ResponseReceived):
                    response_headers = dict(event.headers)
                elif isinstance(event, h2.events.DataReceived):
                    result.extend(event.data)
                    conn.acknowledge_received_data(event.flow_controlled_length, 1)
                elif isinstance(event, h2.events.StreamEnded):
                    complete = True
                elif isinstance(event, h2.events.StreamReset):
                    raise RuntimeError(f'HTTP/2 request reset: {event.error_code}')
            outgoing = conn.data_to_send()
            if outgoing:
                sock.sendall(outgoing)
            if complete:
                return response_headers, bytes(result)
    raise RuntimeError('Incomplete HTTP/2 response')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--singbox-bin', required=True)
    parser.add_argument('--xray-bin', required=True)
    parser.add_argument('--external-handshakes', action='store_true', help='Also test REALITY / ShadowTLS decoy handshakes over the internet')
    parser.add_argument('--only', help='Only run node types containing this text')
    parser.add_argument('--keep', action='store_true', help='Keep logs/configs for debugging (contain generated credentials)')
    args = parser.parse_args()
    target = ThreadingHTTPServer(('0.0.0.0', 0), Target)
    threading.Thread(target=target.serve_forever, daemon=True).start()
    target_port = target.server_port
    failures = []
    tested = []
    with tempfile.TemporaryDirectory(prefix='knight-native-') as tmp:
        data = Path(tmp)
        env = dict(os.environ)
        ports = [free_port() for _ in range(6)]
        while len(set(ports)) != len(ports):
            ports = [free_port() for _ in range(6)]
        env.update(BK_DATA_DIR=str(data), DOMAIN='127.0.0.1', BIND_ADDRESS='127.0.0.1',
                   PORT=str(ports[0]), TLS_PORT=str(ports[1]), SS_PORT=str(ports[2]), WG_PORT=str(ports[3]),
                   HY2_PORT=str(ports[4]), TUIC_PORT=str(ports[5]),
                   PANEL_PASSWORD='native-test-password', SINGBOX_BIN=str(Path(args.singbox_bin).resolve()),
                   XRAY_BIN=str(Path(args.xray_bin).resolve()), ENABLE_HYSTERIA2='true', ENABLE_TUIC='true',
                   ENABLE_SOCKS='true', ENABLE_HTTP_PROXY='true', ENABLE_SHADOWTLS_VLESS='true',
                   ENABLE_ARGO='false', LINK_INSECURE='true', LINK_FP='chrome')
        server = None
        try:
            with (data / 'server.log').open('wb') as server_log:
                server = subprocess.Popen([sys.executable, 'streamlit_app.py', '--no-download', '--stop-file', str(data / 'stop')], cwd=ROOT,
                                           env=env, stdout=server_log, stderr=subprocess.STDOUT)
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError((data / 'server.log').read_text(errors='replace'))
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{ports[0]}/healthz', timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('Python runtime did not become ready')
                cfg = Config.load(env)
                response, _ = h2_request(ports[1], '/knight/login', 'POST', urlencode({'password': env['PANEL_PASSWORD']}).encode(),
                    [('content-type', 'application/x-www-form-urlencoded'), ('origin', f'https://127.0.0.1:{ports[1]}')])
                if response.get(':status') != '302' or 'Secure' not in response.get('set-cookie', ''):
                    raise RuntimeError('HTTPS HTTP/2 sign-in or secure session cookie failed')
                cookie = response['set-cookie'].split(';')[0]
                response, body = h2_request(ports[1], '/knight', headers=[('cookie', cookie)])
                if response.get(':status') != '200' or b'Blue Knight' not in body:
                    raise RuntimeError('HTTP/2 panel rendering failed')
                print('PASS HTTPS HTTP/2 panel and secure sign-in', flush=True)
                state = read_json(data / 'state.json')
                links = Links(cfg, state, {'singbox': True, 'xray': True, 'argo': False})
                all_clients = links.singbox()
                for index, node in enumerate(links.nodes):
                    kind = node['type']
                    if args.only and args.only.lower() not in kind.lower():
                        continue
                    if kind in ('VLESS-REALITY', 'ShadowTLS-VLESS') and not args.external_handshakes:
                        print('SKIP', kind, '(external decoy handshake; opt in with --external-handshakes)', flush=True)
                        continue
                    client_port = free_port()
                    xray = not node['singboxOutbound'] and bool(node['xrayOutbound']) or kind == 'Shadowsocks-WS'
                    if xray:
                        binary = env['XRAY_BIN']
                        config = {'log': {'loglevel': 'warning'},
                                  'inbounds': [{'listen': '127.0.0.1', 'port': client_port, 'protocol': 'http'}],
                                  'outbounds': [node['xrayOutbound']]}
                    else:
                        binary = env['SINGBOX_BIN']
                        config = {'log': {'level': 'debug' if args.keep else 'error'},
                                  'inbounds': [{'type': 'http', 'listen': '127.0.0.1', 'listen_port': client_port}],
                                  'outbounds': node['singboxOutbound'] or [{'type': 'direct', 'tag': 'direct'}],
                                  'route': {'final': node['name']}}
                        if kind == 'WireGuard':
                            config['endpoints'] = all_clients['endpoints']
                    path = data / f'client-{index}.json'
                    path.write_text(json.dumps(config), encoding='utf-8')
                    client = None
                    client_log = data / f'client-{index}.log'
                    try:
                        check = subprocess.run([binary, *(['run', '-test'] if xray else ['check']), '-c', str(path)],
                                               capture_output=True, timeout=15)
                        if check.returncode:
                            raise RuntimeError((check.stdout + check.stderr).decode(errors='replace')[-1200:])
                        with client_log.open('wb') as handle:
                            client = subprocess.Popen([binary, 'run', '-c', str(path)], stdout=handle, stderr=subprocess.STDOUT)
                            last = None
                            for _ in range(3 if kind == 'WireGuard' else 12):
                                if client.poll() is not None:
                                    raise RuntimeError(client_log.read_text(errors='replace')[-1200:])
                                try:
                                    request_through_proxy(client_port, target_port,
                                        socket.gethostbyname(socket.gethostname()) if kind == 'WireGuard' else '127.0.0.1')
                                    if 'GRPC' in kind or 'XHTTP' in kind:
                                        request_through_proxy(client_port, target_port, bulk=True)
                                    last = None
                                    break
                                except OSError as exc:
                                    last = exc
                                    time.sleep(.15)
                            if last:
                                raise last
                        print('PASS', kind, flush=True)
                        tested.append(kind)
                    except Exception as exc:
                        detail = f'{kind}: {exc}; {client_log.read_text(errors="replace")[-800:] if client_log.exists() else ""}'
                        print('FAIL', detail, flush=True)
                        failures.append(detail)
                    finally:
                        terminate(client)
                # Verify that data flows were accounted for by the actual runtime.
                if server.poll() is not None:
                    raise RuntimeError('Runtime crashed during native tests')
                response, body = h2_request(ports[1], '/knight/api/traffic', headers=[('cookie', cookie)])
                if tested and json.loads(body)['allTime']['total'] <= 0:
                    raise RuntimeError('Native traffic was not accounted for')
        finally:
            (data / 'stop').touch()
            if server:
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            terminate(server)
            target.shutdown()
            if args.keep:
                import shutil
                dest = ROOT / '.validation' / 'native-debug'
                shutil.copytree(data, dest, dirs_exist_ok=True)
        # Preserve only a nonsecret result summary in the project validation directory.
        result = {'passed': tested, 'failures': failures,
                  'external_handshakes': args.external_handshakes, 'platform': sys.platform}
        output = ROOT / '.validation' / 'native-result.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'{len(tested)} native proxy tests passed; {len(failures)} failed.', flush=True)
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
