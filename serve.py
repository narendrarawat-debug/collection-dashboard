from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import os, sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

class H(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

print("Serving on http://localhost:8765  (Ctrl+C to stop)")
ThreadingHTTPServer(('', 8765), H).serve_forever()
