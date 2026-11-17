"""The game in a browser beside Blender, on any system: the web build of the engine (Web/README.md) served from this machine
with the scene's files beside it, and told over one stream of events what the Mac window is told over its socket (live.py).

    GET  /                      the page and the web build's files, from a folder or from an address (kept once fetched)
    GET  /live/state            {serial, files, level, lookOverride, camera}: what a page that has just opened needs
    GET  /live/file/<path>      one of the scene's files, laid out as Content/
    GET  /live/events?after=N   server-sent events after serial N: {command, files, removed}
    POST /live/status           what the page says of starting the scene: {ok} or {error}
    POST /live/capture?id=N     a frame the render asked for, as a PNG
    POST /live/log              what the scene's scripts printed, a list of lines

Nothing here touches bpy: the server's threads only move bytes. Only this machine can connect (127.0.0.1)."""
import http.server
import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
         ".wasm": "application/wasm", ".pak": "application/octet-stream", ".jpg": "image/jpeg", ".png": "image/png",
         ".svg": "image/svg+xml", ".css": "text/css; charset=utf-8"}
KEPT_EVENTS = 400
PING = 15

_lock = threading.Condition()
_server = None
_thread = None
_runtime = None
_files = {}
_events = []
_serial = 0
_state = {"level": None, "lookOverride": None, "camera": None}
_status = None
_captures = {}
_listeners = 0
_said = []
KEPT_LINES = 40


class Runtime:
    """The web build: a folder that has it (build/web/site of the repository, an unpacked copy), or the address it is
    served at, whose files are kept in `cache` once fetched (those named by their content, `name?v=hash`, for good)."""

    def __init__(self, source, cache):
        self.source = source.rstrip("/")
        self.cache = cache
        self.remote = self.source.startswith(("http://", "https://"))
        self.problem = None

    def _kept(self, rel, version):
        name = rel.replace("/", "_") + ("@" + version if version else "")
        return os.path.join(self.cache, re.sub(r"[^A-Za-z0-9_.@-]", "_", name))

    def local(self, rel, version=""):
        """The file on this machine if it is here already."""
        if not self.remote:
            path = os.path.join(self.source, *rel.split("/"))
            return path if os.path.isfile(path) else None
        path = self._kept(rel, version)
        # An unversioned file (the page itself) is asked for again each time; the kept copy is for when the address is away.
        return path if version and os.path.isfile(path) else None

    def open(self, rel, version=""):
        """(length, chunks) of a file not here yet: read from the address, kept as it passes through."""
        url = f"{self.source}/{urllib.parse.quote(rel)}" + (f"?v={version}" if version else "")
        kept = self._kept(rel, version)
        try:
            # As it is: Python has no brotli, and the kept copy is served as plain bytes.
            response = urllib.request.urlopen(urllib.request.Request(url, headers={"Accept-Encoding": "identity", "User-Agent": "prism-tools"}), timeout=30)
        except (urllib.error.URLError, OSError) as e:
            self.problem = f"{url}: {e}"
            if os.path.isfile(kept):
                return os.path.getsize(kept), _chunks_of_file(kept)
            return None
        self.problem = None
        length = response.headers.get("Content-Length")

        def chunks():
            os.makedirs(self.cache, exist_ok=True)
            part = kept + f".part{threading.get_ident()}"
            done = False
            try:
                with open(part, "wb") as out:
                    while True:
                        block = response.read(1 << 16)
                        if not block:
                            break
                        out.write(block)
                        yield block
                done = True
            finally:
                response.close()
                if done:
                    os.replace(part, kept)
                elif os.path.exists(part):
                    os.remove(part)
        return (int(length) if length else None), chunks()

    def looked_at(self, script):
        """The page's own script has passed through: a build from before the live link shows its menu and never the scene."""
        if b"live/state" not in script:
            self.problem = f"the game at {self.source} is older than this add-on and cannot show a scene: it has to be published again"

    def data_pak(self):
        """The content pack, when it is on this machine: the page's `data.pak`, whatever version of it was last fetched."""
        if not self.remote:
            return self.local("data.pak")
        if not os.path.isdir(self.cache):
            return None
        found = [os.path.join(self.cache, n) for n in os.listdir(self.cache) if n.startswith("data.pak@") and ".part" not in n]
        return max(found, key=os.path.getmtime) if found else None


def _chunks_of_file(path):
    with open(path, "rb") as f:
        while True:
            block = f.read(1 << 16)
            if not block:
                return
            yield block


_pak_index = (None, None)


def base_files(runtime=None):
    """Paths of the game's own content as the web build packs it (`data.pak`), or None while it is not on this machine:
    path -> (offset, size)."""
    global _pak_index
    r = runtime or _runtime
    path = r.data_pak() if r else None
    if not path:
        return None
    if _pak_index[0] != path:
        index = {}
        try:
            with open(path, "rb") as f:
                if f.read(8) != b"PRISMPAK":
                    return None
                count, = struct.unpack("<I", f.read(4))
                for _ in range(count):
                    n, = struct.unpack("<H", f.read(2))
                    name = f.read(n).decode()
                    at, size = struct.unpack("<II", f.read(8))
                    if name.startswith("data/"):
                        index[name[5:]] = (at, size)
        except (OSError, struct.error, UnicodeDecodeError):
            return None
        _pak_index = (path, index)
    return _pak_index[1]


def base_read(rel, runtime=None):
    """One file of the game's own content, or None."""
    index = base_files(runtime)
    if not index or rel not in index:
        return None
    at, size = index[rel]
    with open(_pak_index[0], "rb") as f:
        f.seek(at)
        return f.read(size)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", kind="application/json; charset=utf-8", cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        query = urllib.parse.parse_qs(url.query)
        try:
            if path == "/live/state":
                with _lock:
                    state = dict(_state, serial=_serial, files=sorted(_files))
                self._send(200, json.dumps(state).encode())
            elif path.startswith("/live/file/"):
                with _lock:
                    data = _files.get(path[len("/live/file/"):])
                if data is None:
                    self._send(404, b"{}")
                else:
                    self._send(200, data, "application/octet-stream")
            elif path == "/live/events":
                self._events(int(query.get("after", ["0"])[0]))
            else:
                self._static(path, query.get("v", [""])[0])
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        global _status
        with _lock:
            if url.path == "/live/status":
                try:
                    _status = json.loads(body or b"{}")
                except ValueError:
                    _status = {"error": "the page sent what is not JSON"}
            elif url.path == "/live/log":
                try:
                    _said.extend(str(line) for line in json.loads(body or b"[]"))
                    del _said[:-KEPT_LINES]
                except (ValueError, TypeError):
                    pass
            elif url.path == "/live/capture":
                _captures[urllib.parse.parse_qs(url.query).get("id", [""])[0]] = body
            _lock.notify_all()
        self._send(204)

    def _static(self, path, version):
        rel = path.lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        if ".." in rel.split("/") or _runtime is None:
            return self._send(404, b"not found", "text/plain")
        kind = TYPES.get(os.path.splitext(rel)[1], "application/octet-stream")
        cache = "public, max-age=31536000, immutable" if version else "no-cache"
        local = _runtime.local(rel, version)
        if local:
            length, chunks = os.path.getsize(local), _chunks_of_file(local)
        elif _runtime.remote:
            opened = _runtime.open(rel, version)
            if opened is None:
                return self._send(502, (_runtime.problem or "no answer").encode(), "text/plain")
            length, chunks = opened
        else:
            return self._send(404, b"not found", "text/plain")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", cache)
        if length is None:
            # Until the connection closes.
            self.send_header("Connection", "close")
            self.close_connection = True
        else:
            self.send_header("Content-Length", str(length))
        self.end_headers()
        script = bytearray() if rel == "prism.js" else None
        for block in chunks:
            self.wfile.write(block)
            if script is not None:
                script += block
        if script is not None:
            _runtime.looked_at(bytes(script))

    def _events(self, after):
        global _listeners
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        server = _server
        with _lock:
            _listeners += 1
        try:
            while _server is server:
                with _lock:
                    waiting = [e for e in _events if e[0] > after]
                    if not waiting:
                        _lock.wait(PING)
                        waiting = [e for e in _events if e[0] > after]
                if not waiting:
                    self.wfile.write(b": still here\n\n")
                for serial, text in waiting:
                    self.wfile.write(b"data: " + text.encode() + b"\n\n")
                    after = serial
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with _lock:
                _listeners -= 1


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def is_on():
    return _server is not None


def address():
    return f"http://127.0.0.1:{_server.server_address[1]}/?live=1" if _server else ""


def runtime():
    return _runtime


def start(port, runtime, files, level, look_override, camera=None):
    """Serves `runtime` with the scene's `files` (path -> bytes). An error message, or None."""
    global _server, _thread, _runtime, _files, _events, _serial, _state, _status
    if _server is not None:
        return "Already on"
    server = None
    # The port may be held by a page of an earlier Blender: the next ones are as good.
    for candidate in range(port, port + 20):
        try:
            server = Server(("127.0.0.1", candidate), Handler)
            break
        except OSError:
            continue
    if server is None:
        return f"No free port from {port}"
    with _lock:
        _runtime = runtime
        _files = dict(files)
        _events = []
        # Past whatever a page left open by an earlier server remembers.
        _serial = int(time.time()) % 1_000_000 * 1000
        _state = {"level": level, "lookOverride": look_override, "camera": camera}
        _status = None
        _captures.clear()
        _said.clear()
    _server = server
    _thread = threading.Thread(target=server.serve_forever, name="prism-web", daemon=True)
    _thread.start()
    return None


def stop():
    global _server, _thread
    server = _server
    _server = None
    if server is not None:
        with _lock:
            _lock.notify_all()
        server.shutdown()
        server.server_close()
    _thread = None


def listeners():
    """Pages that are open on the scene."""
    return _listeners


def status():
    """What the page last said of starting the scene: {"ok": True}, {"error": text}, or None before it has."""
    return _status


def said():
    """The last lines the scene's scripts printed in the page: their own prints and their errors."""
    with _lock:
        return list(_said)


def publish(command=None, files=None, removed=()):
    """A command to every page, and the files (path -> bytes) that changed with it. The state a new page reads goes with it."""
    global _serial, _status
    with _lock:
        for path, data in (files or {}).items():
            _files[path] = data
        for path in removed:
            _files.pop(path, None)
        if command:
            what = command.get("cmd")
            if what == "camera":
                _state["camera"] = command
            elif what == "reload":
                if command.get("level"):
                    _state["level"] = command["level"]
                if "lookOverride" in command:
                    _state["lookOverride"] = command["lookOverride"]
                _status = None
                # What the scripts said of the scene before this one is of no use now.
                _said.clear()
            elif what == "play":
                _state["camera"] = None
                _status = None
        # A camera with nobody watching is only the state.
        if _listeners == 0 and command and command.get("cmd") == "camera" and not files and not removed:
            return
        _serial += 1
        message = {"command": command, "files": sorted(files or {}), "removed": list(removed)}
        _events.append((_serial, json.dumps(message, separators=(",", ":"))))
        del _events[:-KEPT_EVENTS]
        _lock.notify_all()


def capture(command, timeout=60):
    """A frame from a page that is open: PNG bytes, or None when none came in time."""
    if _listeners == 0:
        return None
    key = str(time.monotonic_ns())
    publish(dict(command, cmd="capture", id=key))
    deadline = time.monotonic() + timeout
    with _lock:
        while key not in _captures:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            _lock.wait(left)
        return _captures.pop(key) or None
