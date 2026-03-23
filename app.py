import http.server
import socketserver
import subprocess
import json
import os

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_POST(self):
        if self.path == '/run-scraper':
            try:
                # 가상 환경의 파이썬을 지정하여 스크래퍼 실행
                venv_python = os.path.join(DIRECTORY, '.venv', 'Scripts', 'python.exe')
                scraper_script = os.path.join(DIRECTORY, 'scraper.py')
                
                # 가상환경이 없거나 경로가 다르면 시스템 파이썬 사용 패스백
                python_exec = venv_python if os.path.exists(venv_python) else 'python'
                
                result = subprocess.run([python_exec, scraper_script], capture_output=True, text=True)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                
                response = {
                    "status": "success",
                    "output": result.stdout,
                    "error": result.stderr
                }
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
        elif self.path == '/reset-data':
            try:
                data_path = os.path.join(DIRECTORY, 'data', 'scraped_data.json')
                if os.path.exists(data_path):
                    with open(data_path, 'w', encoding='utf-8') as f:
                        json.dump([], f, ensure_ascii=False)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    os.chdir(DIRECTORY)
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"서버가 http://localhost:{PORT} 에서 실행 중입니다.")
        print("브라우저에서 접속하여 대시보드를 확인하세요.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()

if __name__ == '__main__':
    run_server()
