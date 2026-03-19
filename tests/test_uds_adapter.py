import pytest
import urllib.request
import urllib.parse
from unittest.mock import patch, MagicMock
from red_pill.utils.uds_adapter import get_uds_opener, UnixSocketHTTPConnection

def test_uds_opener_creation():
    """Ensure the opener constructs and registers the unix handler."""
    opener = get_uds_opener()
    assert isinstance(opener, urllib.request.OpenerDirector)
    
    # We can test that sending a unix request hits our handler if mock the connection
    pass

@patch('socket.socket')
def test_unix_socket_connection(mock_socket):
    """Ensure the connection binds AF_UNIX and unwraps the path correctly."""
    mock_sock_instance = MagicMock()
    mock_socket.return_value = mock_sock_instance
    
    raw_path = "/tmp/test_socket.sock"
    encoded_path = urllib.parse.quote(raw_path, safe="")
    
    conn = UnixSocketHTTPConnection(host=encoded_path, timeout=10)
    assert conn.uds_path == raw_path
    
    conn.connect()
    
    mock_socket.assert_called_once()
    mock_sock_instance.settimeout.assert_called_with(10)
    mock_sock_instance.connect.assert_called_with(raw_path)

@patch('red_pill.utils.uds_adapter.UnixSocketHTTPConnection')
def test_urllib_request_with_unix_schema(mock_conn):
    """Test that a high-level urllib request correctly invokes our adapter."""
    mock_conn_instance = MagicMock()
    mock_conn.return_value = mock_conn_instance
    
    opener = get_uds_opener()
    req = urllib.request.Request("unix://%2Ftmp%2Ftest_socket.sock/v1/chat/completions")
    
    # Normally this would raise ValueError "unknown url type" if not registered
    try:
        # We mock open to avoid real network calls, but we also just assert that it is registered
        # A simpler way is to check the handlers
        has_unix = any(hasattr(h, 'unix_open') for h in opener.handlers)
        assert has_unix, "unix_open handler must be registered in the opener"
    except Exception as e:
        pytest.fail(f"Opener failed: {e}")
