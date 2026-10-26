import threading
import unittest
from unittest.mock import Mock, patch

import streamlit_app


class LauncherTests(unittest.TestCase):
    def test_worker_thread_does_not_install_signals(self):
        loop, stop = Mock(), Mock()
        results = []
        worker = threading.Thread(target=lambda: results.append(streamlit_app.install_signal_handlers(loop, stop)))
        with patch('streamlit_app.signal.signal') as fallback:
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results, [False])
            loop.add_signal_handler.assert_not_called()
            fallback.assert_not_called()

    def test_main_thread_installs_handlers(self):
        loop, stop = Mock(), Mock()
        self.assertTrue(streamlit_app.install_signal_handlers(loop, stop))
        self.assertEqual(loop.add_signal_handler.call_count, 2)

    def test_streamlit_reruns_never_launch_engines(self):
        streamlit = Mock()
        runner = Mock()
        runner.get_script_run_ctx.return_value = object()
        with patch.dict('sys.modules', {'streamlit': streamlit, 'streamlit.runtime.scriptrunner': runner}), \
                patch('streamlit_app.asyncio.run') as run:
            streamlit_app.main()
            streamlit_app.main()
            run.assert_not_called()
            self.assertEqual(streamlit.error.call_count, 2)
            self.assertIn('VPS/Docker', streamlit.error.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
