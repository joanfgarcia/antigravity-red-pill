import os
import socket
import json
import logging
import signal
import sys
from fastembed import TextEmbedding
import red_pill.config as cfg

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("memory_daemon")

SOCKET_PATH = "/tmp/red_pill_memory.sock"

class MemoryDaemon:
    def __init__(self):
        self.encoder = None
        self.running = True
        self.server = None

    def _load_model(self):
        if self.encoder is None:
            logger.info(f"Loading FastEmbed model: {cfg.EMBEDDING_MODEL}")
            self.encoder = TextEmbedding(model_name=cfg.EMBEDDING_MODEL)
            logger.info("Model loaded and ready.")

    def start(self):
        # Clean up existing socket
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(SOCKET_PATH)
        # Ensure only the owner can access the socket
        os.chmod(SOCKET_PATH, 0o600)
        self.server.listen(5)
        logger.info(f"Memory Daemon listening on {SOCKET_PATH}")
        
        # Pre-load model to be ready
        try:
            self._load_model()
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            self.stop()

        while self.running:
            try:
                self.server.settimeout(1.0)
                try:
                    conn, _ = self.server.accept()
                except socket.timeout:
                    continue

                with conn:
                    data = conn.recv(4096)
                    if not data:
                        continue
                    
                    try:
                        request = json.loads(data.decode('utf-8'))
                        text = request.get("text")
                        if text:
                            logger.info(f"Processing embedding request: '{text[:30]}...'")
                            # Generate embedding
                            vector = list(self.encoder.embed([text]))[0].tolist()
                            response = {"status": "ok", "vector": vector}
                        elif request.get("command") == "ping":
                            response = {"status": "ok", "message": "pong"}
                        else:
                            response = {"status": "error", "message": "No text provided"}
                    except Exception as e:
                        logger.error(f"Error processing request: {e}")
                        response = {"status": "error", "message": str(e)}

                    conn.sendall(json.dumps(response).encode('utf-8'))
            except Exception as e:
                if self.running:
                    logger.error(f"Daemon loop error: {e}")

    def stop(self, *args):
        if not self.running:
            return
        logger.info("Stopping Memory Daemon...")
        self.running = False
        if self.server:
            try:
                self.server.close()
            except:
                pass
        if os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except:
                pass
        # Note: sys.exit(0) removed to avoid double exit in CLI wrapper

if __name__ == "__main__":
    daemon = MemoryDaemon()
    signal.signal(signal.SIGINT, daemon.stop)
    signal.signal(signal.SIGTERM, daemon.stop)
    daemon.start()
