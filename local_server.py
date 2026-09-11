#!/usr/bin/env python3
import http.server, json, base64, pathlib, urllib.parse, os

OUTPUT_DIR = pathlib.Path("/Users/th28/BGC/Student receipt")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

class Handler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    def do_POST(self):
        if self.path == "/upload":
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                filename = data.get("filename")
                b64 = data.get("base64")
                if not filename or not b64:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"missing filename or base64")
                    return
                # Sanitize filename
                # Keep as is but ensure no path traversal
                safe = filename.replace("/", "_").replace("\\", "_")
                # Ensure .pdf
                if not safe.lower().endswith(".pdf"):
                    safe += ".pdf"
                out_path = OUTPUT_DIR / safe
                # Decode
                pdf_bytes = base64.b64decode(b64)
                # Verify PDF magic
                if not pdf_bytes.startswith(b"%PDF"):
                    # Might have leading \r\n
                    if b"%PDF" in pdf_bytes[:20]:
                        pass
                    else:
                        print(f"Warning: {safe} not PDF magic, first 10: {pdf_bytes[:10]}")
                with open(out_path, "wb") as f:
                    f.write(pdf_bytes)
                print(f"Saved {safe} ({len(pdf_bytes)} bytes)")
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status":"ok", "filename": safe, "size": len(pdf_bytes)}).encode())
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(f"error: {e}".encode())
        else:
            self.send_response(404)
            self.end_headers()
    def do_GET(self):
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            files = list(OUTPUT_DIR.glob("*.pdf"))
            self.wfile.write(json.dumps({"count": len(files), "files": [f.name for f in files]}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        print("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format%args))

if __name__ == "__main__":
    server_address = ('127.0.0.1', 8765)
    httpd = http.server.HTTPServer(server_address, Handler)
    print(f"Serving on http://{server_address[0]}:{server_address[1]}")
    httpd.serve_forever()
