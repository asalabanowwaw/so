"""Blue Knight Gate Python. Start the complete server with `python streamlit_app.py`."""
import argparse
import asyncio
import logging
import signal
import threading

from aiohttp import web
from dotenv import load_dotenv

from knight.config import Config
from knight.engines import Supervisor, allocate_ports, build_singbox, build_xray, install_binary
from knight.network import Router
from knight.storage import Auth, ensure_certificate, initialize_state, write_json
from knight.traffic import Traffic
from knight.web import make_app

log = logging.getLogger('knight')


def install_signal_handlers(loop, stop):
    """Signals belong to the main interpreter thread, never a framework worker."""
    if threading.current_thread() is not threading.main_thread():
        log.warning('Worker-thread runtime: signal handlers are disabled; use --stop-file for graceful shutdown')
        return False
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    return True


def show_streamlit_notice():
    """Do not start standalone servers on each Streamlit session/rerun."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        return False
    if get_script_run_ctx(suppress_warning=True) is None:
        return False
    import streamlit as st
    st.set_page_config(page_title='Blue Knight — deployment', page_icon='♞')
    st.title('Blue Knight Gate')
    st.error('This upload contains the complete VPS/Docker server. It cannot run as a Streamlit Community Cloud app.')
    st.write('Streamlit serves its own application on port 8501. The Blue Knight panel, subscription routes, '
             'and proxy TCP/UDP listeners are separate services and are not published by this deployment.')
    st.write('Deploy this repository on your VPS with Docker Compose:')
    st.code('cp .env.example .env\n# Set DOMAIN and PANEL_PASSWORD in .env\ndocker compose up -d --build', language='bash')
    st.write('Or start it directly on a VPS:')
    st.code('python streamlit_app.py', language='bash')
    st.caption('No proxy cores or extra listeners have been started by this Streamlit page.')
    return True


async def run(args):
    cfg = Config.load()
    cfg.data.mkdir(parents=True, exist_ok=True)
    if args.install_engines:
        for name in ('singbox', 'xray', 'argo'):
            await asyncio.to_thread(install_binary, cfg, name)
        return
    state = initialize_state(cfg)
    auth = Auth(cfg)
    ensure_certificate(cfg)
    ports = allocate_ports()
    if args.generate_only:
        write_json(cfg.data / 'sing-box.json', build_singbox(cfg, state, ports))
        write_json(cfg.data / 'xray.json', build_xray(cfg, state, ports))
        log.info('Engine configs generated in %s (no listeners or processes started)', cfg.data)
        return
    supervisor = Supervisor(cfg)
    await supervisor.prepare(state, ports, install=not args.no_download, validate_only=args.check)
    if args.check:
        log.info('All enabled engine configurations passed native validation')
        return
    traffic = Traffic(cfg)
    runner = web.AppRunner(make_app(cfg, state, auth, traffic, supervisor), access_log=None)
    router = Router(cfg, ports, traffic, supervisor)
    meter = None
    try:
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', ports['web']).start()
        await supervisor.start()
        await router.start()
        meter = asyncio.create_task(traffic.run())
        log.info('Blue Knight Gate Python is ready. Panel: https://%s:%s/%s',
                 cfg.advertised_host(state), cfg.tls_port, cfg.panel)
        if not auth.data.get('hash'):
            log.info('First-time setup key is stored in %s; use it to create the panel password', cfg.data / 'setup-key.txt')
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        install_signal_handlers(loop, stop)
        async def watch_stop_file():
            from pathlib import Path
            while not stop.is_set():
                if Path(args.stop_file).exists():
                    stop.set()
                    return
                await asyncio.sleep(.2)
        watcher = asyncio.create_task(watch_stop_file()) if args.stop_file else None
        try:
            await stop.wait()
        finally:
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
    finally:
        await router.close()
        await supervisor.close()
        if meter:
            meter.cancel()
            await asyncio.gather(meter, return_exceptions=True)
        traffic.save()
        await runner.cleanup()


def main():
    if show_streamlit_notice():
        return
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent / '.env')
    parser = argparse.ArgumentParser(description='Complete Blue Knight Gate server for VPS / Docker')
    parser.add_argument('--install-engines', action='store_true', help='Install pinned native cores and exit')
    parser.add_argument('--no-download', action='store_true', help='Require preinstalled cores')
    parser.add_argument('--check', action='store_true', help='Generate and validate native engine configurations, then exit')
    parser.add_argument('--generate-only', action='store_true', help='Generate configs without downloading or running cores')
    parser.add_argument('--stop-file', help='Gracefully stop when this local file is created (useful for Windows services)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        log.error('Startup failed: %s', exc)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
