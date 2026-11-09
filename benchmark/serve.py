"""Local-only static/SPA serving for reproducible benchmark builds."""
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_head(self):
        route = urlsplit(self.path).path
        if not Path(self.translate_path(route)).exists() and not Path(route).suffix:
            self.path = '/index.html'
        return super().send_head()


@contextmanager
def serve(directory):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(directory)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
