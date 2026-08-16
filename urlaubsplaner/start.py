#!/usr/bin/env python3
"""Startet den Urlaubsplaner auf einem lokalen Webserver und öffnet den Browser.

Aufruf:
    python start.py            # Port 8000
    python start.py 8080       # eigener Port

Der Umweg über einen lokalen Server hat einen praktischen Grund: Chrome behandelt
Dateien, die per Doppelklick geöffnet werden, je nach Version als eigene Herkunft.
Der gespeicherte Plan wäre dann unter Umständen beim nächsten Start weg. Über
http://localhost bleiben die Daten zuverlässig erhalten.
"""

import http.server
import os
import socketserver
import sys
import threading
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        # Der Planer fragt beim Start, ob ein Sync-Server läuft. Hier läuft
        # keiner – die klare Antwort erspart eine Fehlermeldung in der Konsole.
        if self.path.split("?")[0] == "/api/ping":
            body = b'{"sync":false,"server":"start.py"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        # Beim Entwickeln soll immer die aktuelle Datei ausgeliefert werden.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # Konsole ruhig halten


def main():
    socketserver.TCPServer.allow_reuse_address = True
    port = PORT
    for attempt in range(20):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        print(f"Kein freier Port zwischen {PORT} und {PORT + 19} gefunden.")
        return 1

    url = f"http://localhost:{port}/index.html"
    print("Urlaubsplaner laeuft.")
    print(f"  {url}")
    print("Beenden mit Strg+C")

    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
