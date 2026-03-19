import socket
import urllib.request
import urllib.parse
from http.client import HTTPConnection

class UnixSocketHTTPConnection(HTTPConnection):
    def __init__(self, host, port=None, timeout=60, **kwargs):
        super().__init__("localhost", port, timeout, **kwargs)
        self.uds_path = urllib.parse.unquote(host)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.uds_path)

class UnixSocketHandler(urllib.request.AbstractHTTPHandler):
    def unix_open(self, req):
        return self.do_open(UnixSocketHTTPConnection, req)

def get_uds_opener():
    """Returns a urllib opener capable of handling unix:// URLs."""
    return urllib.request.build_opener(UnixSocketHandler())
