import json
import time
from threading import Event, Thread
from typing import cast

from websockets.sync.server import ServerConnection, serve

from busybar_codex.config import Config
from busybar_codex.inputs import DeviceInputs


def test_input_stream_decodes_protobuf_defaults_and_stops() -> None:
    release = Event()
    handshakes: list[object] = []

    def handler(connection: ServerConnection) -> None:
        handshakes.append(json.loads(connection.recv(timeout=3)))
        # State.updates -> StateUpdate.input -> START/PRESS (action=0 omitted).
        connection.send(b"\x12\x06\x5a\x04\x0a\x02\x08\x02")
        # Encoder delta=-2, zigzag encoded as 3.
        connection.send(b"\x12\x06\x5a\x04\x1a\x02\x08\x03")
        release.wait(5)

    with serve(handler, "127.0.0.1", 0) as server:
        port = cast(tuple[str, int], server.socket.getsockname())[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        receiver = DeviceInputs(Config(base_url=f"http://127.0.0.1:{port}"))
        receiver.start()
        received: list[str | int] = []
        try:
            deadline = time.monotonic() + 4
            while len(received) < 2 and time.monotonic() < deadline:
                received.extend(receiver.drain())
                time.sleep(0.02)
            assert handshakes == [{"enable": True}]
            assert received == ["dismiss", -2]
        finally:
            release.set()
            receiver.close()
            server.shutdown()
            thread.join(timeout=3)
        assert receiver.thread is not None and not receiver.thread.is_alive()
