"""Generate connection URIs and real client configuration files."""
import base64
import json
from urllib.parse import quote, urlencode

import yaml

from .config import PATHS, GRPC, TROJAN_GRPC, boolean


def b64(value):
    return base64.b64encode(value.encode()).decode()


def authority(host):
    return f'[{host}]' if ':' in host else host


class Links:
    def __init__(self, cfg, state, status, argo_domain=''):
        self.cfg, self.state, self.status = cfg, state, status
        self.host = cfg.advertised_host(state)
        self.argo = argo_domain
        self.nodes = []
        self.insecure = boolean(cfg.env, 'LINK_INSECURE', not bool(cfg.env.get('TLS_CERT')))
        self.sni = cfg.env.get('LINK_SNI') or cfg.domain or self.host
        self.host_header = cfg.env.get('LINK_HOST') or self.sni
        self.fp = cfg.env.get('LINK_FP', 'chrome')
        self.uid = state['uuid']
        self.build()

    def append(self, kind, uri, clash=None, sb=None, xray=None, compat=True, **extras):
        name = self.cfg.env.get('NODE_PREFIX', '💞t.me/BlueKnight_Net - ') + kind
        self.nodes.append({'name': name, 'type': kind, 'compat': compat, 'uri': uri + '#' + quote(name, safe=''),
                           'clash': dict(clash, name=name) if clash else None,
                           'singboxOutbound': [dict(v, tag=name if i == 0 else name + '-tls') for i, v in enumerate(sb or [])],
                           'xrayOutbound': dict(xray, tag=name) if xray else None, **extras})
        self.nodes[-1]['singboxJson'] = json.dumps(self.nodes[-1]['singboxOutbound'], indent=2) if sb else None

    def tls(self, sni=None, insecure=None):
        result = {'enabled': True, 'server_name': sni or self.sni,
                  'insecure': self.insecure if insecure is None else insecure}
        if self.fp not in ('', 'none', 'off'):
            result['utls'] = {'enabled': True, 'fingerprint': self.fp}
        return result

    def transport(self, protocol, network, secure, key, kind=None, host=None, port=None):
        host, port = host or self.host, port or (self.cfg.tls_port if secure else self.cfg.port)
        path = (TROJAN_GRPC if protocol == 'trojan' else GRPC) if network == 'grpc' else PATHS[key]
        kind = kind or protocol.upper().replace('VMESS', 'VMess').replace('TROJAN', 'Trojan') + '-' + network.upper() + ('-TLS' if secure else '')
        sni = host if host != self.host else self.sni
        host_header = host if host != self.host else self.host_header
        query = {'encryption': 'none', 'security': 'tls' if secure else 'none', 'type': network}
        if secure:
            query.update(sni=sni, fp=self.fp, alpn='h2' if network in ('grpc', 'xhttp') else 'http/1.1',
                         allowInsecure='1' if self.insecure and host == self.host else '0')
        query.update({'serviceName': path, 'mode': 'gun'} if network == 'grpc' else {'path': path, 'host': host_header})
        if network == 'xhttp':
            query['mode'] = 'auto'
        if protocol == 'vmess':
            uri = 'vmess://' + b64(json.dumps({'v': '2', 'ps': kind, 'add': host, 'port': str(port), 'id': self.uid,
                'aid': '0', 'scy': 'auto', 'net': network, 'type': 'none', 'host': host_header, 'path': path,
                'tls': 'tls' if secure else '', 'sni': sni, 'fp': self.fp, 'alpn': 'http/1.1',
                'allowInsecure': '1' if self.insecure and host == self.host else '0'}, separators=(',', ':')))
        else:
            uri = f'{protocol}://{quote(self.uid, safe="")}@{authority(host)}:{port}?' + urlencode(query)
        sb = {'type': protocol, 'server': host, 'server_port': port,
              **({'password': self.uid} if protocol == 'trojan' else {'uuid': self.uid})}
        if protocol == 'vmess':
            sb.update(security='auto', alter_id=0)
        if network == 'grpc':
            sb['transport'] = {'type': 'grpc', 'service_name': path}
        else:
            sb['transport'] = {'type': network, 'path': path, 'headers': {'Host': host_header}}
            if network == 'httpupgrade':
                sb['transport'] = {'type': network, 'path': path, 'host': host_header}
        if secure:
            sb['tls'] = self.tls(sni, self.insecure if host == self.host else False)
            sb['tls']['alpn'] = ['h2' if network == 'grpc' else 'http/1.1']
        clash = {'type': protocol, 'server': host, 'port': port, 'udp': True,
                 **({'password': self.uid} if protocol == 'trojan' else {'uuid': self.uid}), 'network': network,
                 'tls': secure, 'servername': sni, 'skip-cert-verify': self.insecure if host == self.host else False}
        if protocol == 'vmess':
            clash.update(cipher='auto', alterId=0)
        if network == 'ws':
            clash['ws-opts'] = {'path': path, 'headers': {'Host': host_header}}
        elif network == 'grpc':
            clash['grpc-opts'] = {'grpc-service-name': path}
        else:
            clash = None  # No unverified HTTPUpgrade/XHTTP syntax in a Mihomo subscription.
        settings = ({'servers': [{'address': host, 'port': port, 'password': self.uid}]} if protocol == 'trojan' else
                    {'vnext': [{'address': host, 'port': port, 'users': [{'id': self.uid,
                        **({'encryption': 'none'} if protocol == 'vless' else {'security': 'auto', 'alterId': 0})}]}]})
        stream = {'network': network, 'security': 'tls' if secure else 'none'}
        stream[{'ws': 'wsSettings', 'grpc': 'grpcSettings', 'httpupgrade': 'httpupgradeSettings', 'xhttp': 'xhttpSettings'}[network]] = (
            {'serviceName': path} if network == 'grpc' else {'path': path, 'host': host_header} if network != 'ws' else
            {'path': path, 'headers': {'Host': host_header}})
        if network == 'xhttp':
            stream['xhttpSettings']['mode'] = 'auto'
        if secure:
            stream['tlsSettings'] = {'serverName': sni, 'allowInsecure': self.insecure if host == self.host else False,
                                      'fingerprint': self.fp, 'alpn': ['h2' if network in ('grpc', 'xhttp') else 'http/1.1']}
        self.append(kind, uri, clash, [sb] if network != 'xhttp' else None,
                    {'protocol': protocol, 'settings': settings, 'streamSettings': stream},
                    note='Use Xray/v2rayN for XHTTP; sing-box 1.11 does not support this transport.' if network == 'xhttp' else None)

    def build(self):
        c, s, e = self.cfg, self.state, self.cfg.enable
        if self.status.get('singbox'):
            for key, proto in [('vlessWs', 'vless'), ('vmessWs', 'vmess'), ('trojanWs', 'trojan')]:
                for secure in (False, True):
                    if e[key + ('Tls' if secure else '')]:
                        self.transport(proto, 'ws', secure, key)
            for key, proto in [('vlessHu', 'vless'), ('vmessHu', 'vmess'), ('trojanHu', 'trojan')]:
                if e[key]:
                    self.transport(proto, 'httpupgrade', False, key)
                    self.transport(proto, 'httpupgrade', True, key)
            if e['vlessGrpc']:
                self.transport('vless', 'grpc', False, 'vlessGrpc')
            if e['vlessGrpcTls']:
                self.transport('vless', 'grpc', True, 'vlessGrpc')
            if e['trojanGrpcTls']:
                self.transport('trojan', 'grpc', True, 'trojanGrpc')
            if e['reality']:
                query = {'security': 'reality', 'sni': c.reality_sni, 'fp': 'chrome', 'pbk': s['realityPublicKey'],
                         'sid': s['realityShortId'], 'type': 'tcp', 'flow': 'xtls-rprx-vision', 'encryption': 'none'}
                sb = {'type': 'vless', 'server': self.host, 'server_port': c.tls_port, 'uuid': self.uid, 'flow': 'xtls-rprx-vision',
                      'tls': {'enabled': True, 'server_name': c.reality_sni, 'utls': {'enabled': True, 'fingerprint': 'chrome'},
                              'reality': {'enabled': True, 'public_key': s['realityPublicKey'], 'short_id': s['realityShortId']}}}
                clash = {'type': 'vless', 'server': self.host, 'port': c.tls_port, 'uuid': self.uid, 'tls': True,
                         'flow': 'xtls-rprx-vision', 'servername': c.reality_sni, 'client-fingerprint': 'chrome',
                         'reality-opts': {'public-key': s['realityPublicKey'], 'short-id': s['realityShortId']}}
                xr = {'protocol': 'vless', 'settings': {'vnext': [{'address': self.host, 'port': c.tls_port,
                    'users': [{'id': self.uid, 'encryption': 'none', 'flow': 'xtls-rprx-vision'}]}]},
                    'streamSettings': {'network': 'tcp', 'security': 'reality', 'realitySettings': {
                        'serverName': c.reality_sni, 'fingerprint': 'chrome', 'publicKey': s['realityPublicKey'], 'shortId': s['realityShortId']}}}
                self.append('VLESS-REALITY', f'vless://{self.uid}@{authority(self.host)}:{c.tls_port}?' + urlencode(query), clash, [sb], xr)
            if e['shadowsocks']:
                self.shadowsocks(False)
            if e['shadowTls']:
                name = c.env.get('NODE_PREFIX', '💞t.me/BlueKnight_Net - ') + 'ShadowTLS-VLESS'
                vless = {'type': 'vless', 'server': self.host, 'server_port': c.tls_port, 'uuid': self.uid, 'detour': name + '-tls'}
                shadow = {'type': 'shadowtls', 'server': self.host, 'server_port': c.tls_port, 'version': 3,
                          'password': s['shadowTlsPassword'], 'tls': self.tls(c.shadow_sni, False)}
                self.append('ShadowTLS-VLESS', f'shadowtls://{quote(s["shadowTlsPassword"], safe="")}@{authority(self.host)}:{c.tls_port}?'+urlencode({'sni': c.shadow_sni, 'version': 3}),
                            sb=[vless, shadow], compat=False, note='Import the sing-box JSON to preserve the VLESS-over-ShadowTLS chain.')
            if e['wireguard']:
                conf = self.wireguard_conf()
                clash = {'type': 'wireguard', 'server': self.host, 'port': c.wg_port,
                         'ip': c.env.get('WG_CLIENT_IP', '10.66.66.2/32').split('/')[0],
                         'private-key': s['wireguardClientPrivateKey'], 'public-key': s['wireguardPublicKey'],
                         'udp': True, 'mtu': int(c.env.get('WG_MTU', 1420))}
                self.append('WireGuard', 'wireguard://' + quote(s['wireguardClientPrivateKey'], safe='') +
                            f'@{authority(self.host)}:{c.wg_port}?' + urlencode({'publickey': s['wireguardPublicKey']}),
                            clash, compat=False, wgConf=conf, note='Import wg0.conf in the official WireGuard client.')
            for key, scheme, port in [('hysteria2', 'hysteria2', c.hy_port), ('tuic', 'tuic', c.tuic_port)]:
                if not e[key]:
                    continue
                sb = {'type': key, 'server': self.host, 'server_port': port, 'password': self.uid, 'tls': self.tls()}
                clash = {'type': key, 'server': self.host, 'port': port, 'password': self.uid,
                         'sni': self.sni, 'skip-cert-verify': self.insecure, 'udp': True}
                query = {'sni': self.sni, 'insecure': '1' if self.insecure else '0', 'alpn': 'h3'}
                credentials = self.uid
                if key == 'tuic':
                    credentials += ':' + self.uid
                    sb.update(uuid=self.uid, congestion_control=c.env.get('TUIC_CC', 'bbr'))
                    clash.update(uuid=self.uid, **{'congestion-controller': c.env.get('TUIC_CC', 'bbr'), 'alpn': ['h3']})
                else:
                    sb['obfs'] = {'type': 'salamander', 'password': s['hy2ObfsPassword']}
                    clash.update(obfs='salamander', **{'obfs-password': s['hy2ObfsPassword']})
                    query.update(obfs='salamander', **{'obfs-password': s['hy2ObfsPassword']})
                sb['tls']['alpn'] = ['h3']
                sb['tls'].pop('utls', None)  # QUIC uses its own TLS stack.
                self.append('TUIC' if key == 'tuic' else 'Hysteria2', f'{scheme}://{credentials}@{authority(self.host)}:{port}?' + urlencode(query), clash, [sb], compat=key != 'tuic')
            for key, scheme, prefix in [('socks', 'socks', 'SOCKS'), ('httpProxy', 'http', 'HTTP_PROXY')]:
                if e[key]:
                    user, password = c.env.get(prefix + '_USER') or 'knight', c.env.get(prefix + '_PASSWORD') or self.uid
                    sb = {'type': scheme, 'server': self.host, 'server_port': c.port, 'username': user, 'password': password}
                    clash = {'type': 'socks5' if key == 'socks' else 'http', 'server': self.host, 'port': c.port,
                             'username': user, 'password': password}
                    self.append('SOCKS5' if key == 'socks' else 'HTTP-Proxy', f'{scheme}://{quote(user, safe="")}:{quote(password, safe="")}@{authority(self.host)}:{c.port}', clash, [sb], compat=False)
        if self.status.get('xray'):
            if e['xhttp']:
                for secure in (False, True):
                    self.transport('vless', 'xhttp', secure, 'xhttp')
            if e['ssWs']:
                self.shadowsocks(True)
        if self.status.get('argo') and self.argo and self.status.get('singbox') and (e['vlessWs'] or e['vlessWsTls']):
            self.transport('vless', 'ws', True, 'vlessWs', kind='VLESS-ARGO', host=self.argo, port=443)

    def shadowsocks(self, websocket):
        c, s = self.cfg, self.state
        method, password = c.env.get('SS_METHOD', 'aes-256-gcm'), s['shadowsocksPassword']
        port = c.tls_port if websocket else c.ss_port
        uri = f'ss://{b64(method + ":" + password)}@{authority(self.host)}:{port}'
        sb = {'type': 'shadowsocks', 'server': self.host, 'server_port': port, 'method': method, 'password': password}
        clash = {'type': 'ss', 'server': self.host, 'port': port, 'cipher': method, 'password': password, 'udp': not websocket}
        xr = {'protocol': 'shadowsocks', 'settings': {'servers': [{'address': self.host, 'port': port, 'method': method, 'password': password}]}}
        if websocket:
            options = f'tls;host={self.host_header};path={PATHS["ssWs"]}'
            if self.insecure:
                options += ';skip-cert-verify'
            uri += '?' + urlencode({'plugin': 'v2ray-plugin;' + options})
            sb.update(plugin='v2ray-plugin', plugin_opts=options.replace('server;', ''))
            clash.update(plugin='v2ray-plugin', **{'plugin-opts': {'mode': 'websocket', 'tls': True,
                          'host': self.host_header, 'path': PATHS['ssWs'], 'skip-cert-verify': self.insecure}})
            xr['streamSettings'] = {'network': 'ws', 'security': 'tls', 'wsSettings': {'path': PATHS['ssWs'], 'headers': {'Host': self.host_header}},
                                    'tlsSettings': {'serverName': self.sni, 'allowInsecure': self.insecure}}
        self.append('Shadowsocks-WS' if websocket else 'Shadowsocks', uri, clash, [sb], xr,
                    note='The sing-box client needs v2ray-plugin installed for this node.' if websocket else None)

    def wireguard_conf(self):
        c, s = self.cfg, self.state
        return '\n'.join(['[Interface]', 'PrivateKey = ' + s['wireguardClientPrivateKey'],
            'Address = ' + c.env.get('WG_CLIENT_IP', '10.66.66.2/32'), 'DNS = 1.1.1.1, 8.8.8.8',
            'MTU = ' + c.env.get('WG_MTU', '1420'), '', '[Peer]', 'PublicKey = ' + s['wireguardPublicKey'],
            f'Endpoint = {authority(self.host)}:{c.wg_port}', 'AllowedIPs = 0.0.0.0/0', 'PersistentKeepalive = 25', ''])

    def public_nodes(self, compat='full'):
        nodes = self.nodes if compat == 'full' else [n for n in self.nodes if n['compat']]
        return [{k: v for k, v in node.items() if k not in ('clash', 'singboxOutbound', 'xrayOutbound')} for node in nodes]

    def raw(self, compat='v2ray'):
        return '\n'.join(n['uri'] for n in self.nodes if compat == 'full' or n['compat'])

    def clash(self):
        proxies = [n['clash'] for n in self.nodes if n['clash']]
        names = [n['name'] for n in self.nodes if n['clash']]
        return yaml.safe_dump({'mixed-port': 7890, 'allow-lan': False, 'mode': 'rule', 'log-level': 'info',
            'proxies': proxies, 'proxy-groups': [{'name': 'BlueKnight', 'type': 'select', 'proxies': names + ['DIRECT']}],
            'rules': ['MATCH,BlueKnight']}, allow_unicode=True, sort_keys=False)

    def singbox(self):
        outbounds = [out for node in self.nodes for out in node['singboxOutbound']]
        endpoints = []
        if self.cfg.enable['wireguard'] and self.status.get('singbox'):
            name = next(n['name'] for n in self.nodes if n['type'] == 'WireGuard')
            endpoints = [{'type': 'wireguard', 'tag': name, 'system': False,
                          'address': [self.cfg.env.get('WG_CLIENT_IP', '10.66.66.2/32')],
                          'private_key': self.state['wireguardClientPrivateKey'],
                          'peers': [{'address': self.host, 'port': self.cfg.wg_port,
                                     'public_key': self.state['wireguardPublicKey'], 'allowed_ips': ['0.0.0.0/0']}]}]
        names = [n['name'] for n in self.nodes if n['singboxOutbound']] + [v['tag'] for v in endpoints]
        result = {'log': {'level': 'info'}, 'inbounds': [{'type': 'mixed', 'tag': 'mixed-in', 'listen': '127.0.0.1', 'listen_port': 2080}],
                  'outbounds': [{'type': 'selector', 'tag': 'BlueKnight', 'outbounds': names + ['direct']}, *outbounds,
                                {'type': 'direct', 'tag': 'direct'}], 'route': {'final': 'BlueKnight'}}
        if endpoints:
            result['endpoints'] = endpoints
        return result

    def xray(self):
        outbounds = [n['xrayOutbound'] for n in self.nodes if n['xrayOutbound']]
        return {'log': {'loglevel': 'warning'}, 'inbounds': [{'tag': 'socks-in', 'listen': '127.0.0.1', 'port': 1080,
                'protocol': 'socks', 'settings': {'udp': True}}],
                'outbounds': outbounds + [{'protocol': 'freedom', 'tag': 'direct'}]}
