"""HTTP/2 stream demultiplexer for gRPC and XHTTP, with flow control."""
import asyncio
from contextlib import suppress

import h2.config
import h2.connection
import h2.events
import h2.exceptions
import aiohttp


class Endpoint:
    def __init__(self, writer, server):
        self.writer = writer
        self.conn = h2.connection.H2Connection(h2.config.H2Configuration(client_side=not server, header_encoding='utf-8'))
        self.window = asyncio.Event()
        self.window.set()

    async def flush(self):
        data = self.conn.data_to_send()
        if data:
            self.writer.write(data)
            await self.writer.drain()

    async def send(self, stream, data):
        view = memoryview(data)
        while view:
            size = min(len(view), self.conn.max_outbound_frame_size, self.conn.local_flow_control_window(stream))
            if size <= 0:
                self.window.clear()
                await self.window.wait()
                continue
            self.conn.send_data(stream, view[:size].tobytes())
            view = view[size:]
            await self.flush()


async def serve_h2(reader, writer, resolve, traffic, initial=b'', peer='unknown', scheme='https'):
    front = Endpoint(writer, True)
    front.conn.initiate_connection()
    await front.flush()
    streams = {}
    tasks = set()

    async def web_stream(stream_id, headers, queue, target):
        """Translate ordinary browser HTTP/2 requests to the loopback HTTP/1 app."""
        values = dict(headers)
        request_headers = {k: v for k, v in headers if not k.startswith((':', 'x-bk-', 'x-forwarded-'))
                           and k not in ('connection', 'transfer-encoding', 'upgrade', 'host')}
        request_headers.update({'Host': values.get(':authority', 'localhost'), 'X-BK-Client-IP': peer,
                                'X-BK-Scheme': scheme})

        async def body():
            while True:
                event = await queue.get()
                if event is None or isinstance(event, h2.events.TrailersReceived):
                    return
                yield event.data
                front.conn.acknowledge_received_data(event.flow_controlled_length, stream_id)
                await front.flush()

        method = values.get(':method', 'GET')
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, auto_decompress=False) as client:
            async with client.request(method, f'http://127.0.0.1:{target}' + values.get(':path', '/'),
                    headers=request_headers, data=body() if method not in ('GET', 'HEAD') else None,
                    allow_redirects=False) as response:
                response_headers = [(':status', str(response.status))] + [
                    (k.decode('latin1').lower(), v.decode('latin1')) for k, v in response.raw_headers
                    if k.lower() not in (b'connection', b'transfer-encoding', b'keep-alive', b'upgrade')]
                front.conn.send_headers(stream_id, response_headers)
                await front.flush()
                if method != 'HEAD':
                    async for chunk in response.content.iter_chunked(32768):
                        await front.send(stream_id, chunk)
                front.conn.end_stream(stream_id)
                await front.flush()

    async def stream_proxy(stream_id, headers, queue, target, label):
        back_writer = None
        sender = None
        metered = label != '__web__'
        if metered:
            traffic.active[label] = traffic.active.get(label, 0) + 1
        try:
            if not metered:
                await web_stream(stream_id, headers, queue, target)
                return
            back_reader, back_writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', target), 5)
            back = Endpoint(back_writer, False)
            back.conn.initiate_connection()
            # Each incoming stream owns an upstream connection. Reuse its single stream ID 1.
            back.conn.send_headers(1, [(k, 'http' if k == ':scheme' else v) for k, v in headers
                                      if k not in ('connection', 'transfer-encoding', 'upgrade')])
            await back.flush()

            async def send_request():
                while True:
                    event = await queue.get()
                    if event is None:
                        back.conn.end_stream(1)
                        await back.flush()
                        return
                    if isinstance(event, h2.events.TrailersReceived):
                        back.conn.send_headers(1, event.headers, end_stream=True)
                        await back.flush()
                        return
                    await back.send(1, event.data)
                    traffic.add(label, up=len(event.data))
                    front.conn.acknowledge_received_data(event.flow_controlled_length, stream_id)
                    await front.flush()

            sender = asyncio.create_task(send_request())
            while data := await back_reader.read(65536):
                for event in back.conn.receive_data(data):
                    if isinstance(event, (h2.events.WindowUpdated, h2.events.RemoteSettingsChanged)):
                        back.window.set()
                    elif isinstance(event, (h2.events.ResponseReceived, h2.events.InformationalResponseReceived)):
                        front.conn.send_headers(stream_id, event.headers)
                    elif isinstance(event, h2.events.DataReceived):
                        await front.send(stream_id, event.data)
                        traffic.add(label, down=len(event.data))
                        back.conn.acknowledge_received_data(event.flow_controlled_length, 1)
                    elif isinstance(event, h2.events.TrailersReceived):
                        front.conn.send_headers(stream_id, event.headers, end_stream=True)
                    elif isinstance(event, h2.events.StreamEnded):
                        with suppress(h2.exceptions.StreamClosedError):
                            front.conn.end_stream(stream_id)
                        await front.flush()
                        return
                    elif isinstance(event, (h2.events.StreamReset, h2.events.ConnectionTerminated)):
                        raise ConnectionError('Upstream stream closed')
                await front.flush()
                await back.flush()
            raise ConnectionError('Upstream disconnected')
        except (OSError, h2.exceptions.H2Error, asyncio.TimeoutError, aiohttp.ClientError):
            with suppress(h2.exceptions.H2Error, OSError):
                front.conn.reset_stream(stream_id, error_code=2)
                await front.flush()
        finally:
            if metered:
                traffic.active[label] = max(0, traffic.active.get(label, 1) - 1)
            streams.pop(stream_id, None)
            if sender:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
            if back_writer:
                back_writer.close()
                with suppress(OSError):
                    await back_writer.wait_closed()

    try:
        data = initial
        while True:
            if not data:
                data = await reader.read(65536)
            if not data:
                break
            for event in front.conn.receive_data(data):
                if isinstance(event, h2.events.RequestReceived):
                    path = dict(event.headers).get(':path', '')
                    target, label = resolve(path)
                    if not target or len(streams) >= 100:
                        front.conn.send_headers(event.stream_id, [(':status', '404' if not target else '429')], end_stream=True)
                        continue
                    queue = asyncio.Queue()
                    task = asyncio.create_task(stream_proxy(event.stream_id, event.headers, queue, target, label))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                    streams[event.stream_id] = (queue, task)
                elif isinstance(event, h2.events.DataReceived):
                    if event.stream_id in streams:
                        streams[event.stream_id][0].put_nowait(event)
                    else:
                        front.conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                elif isinstance(event, h2.events.TrailersReceived):
                    if event.stream_id in streams:
                        streams[event.stream_id][0].put_nowait(event)
                elif isinstance(event, h2.events.StreamEnded):
                    if event.stream_id in streams:
                        streams[event.stream_id][0].put_nowait(None)
                elif isinstance(event, h2.events.StreamReset):
                    if event.stream_id in streams:
                        streams[event.stream_id][1].cancel()
                elif isinstance(event, (h2.events.WindowUpdated, h2.events.RemoteSettingsChanged)):
                    front.window.set()
                elif isinstance(event, h2.events.ConnectionTerminated):
                    return
            await front.flush()
            data = b''
    except (OSError, h2.exceptions.H2Error):
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
