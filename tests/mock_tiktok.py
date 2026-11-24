import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
STATE={"bytes":0,"size":None,"puts":[]}
PUBLIC = len(sys.argv)>2 and sys.argv[2]=="audited"
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _j(self,obj,code=200):
        b=json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n=int(self.headers.get("Content-Length",0)); body=self.rfile.read(n)
        ok={"error":{"code":"ok","message":"","log_id":"x"}}
        if self.path=="/v2/oauth/token/":
            return self._j({"access_token":"AT","refresh_expires_in":31536000})
        assert self.headers["Authorization"]=="Bearer AT"
        if self.path=="/v2/post/publish/creator_info/query/":
            opts=["PUBLIC_TO_EVERYONE","SELF_ONLY"] if PUBLIC else ["SELF_ONLY"]
            return self._j({"data":{"privacy_level_options":opts,"max_video_post_duration_sec":600},**ok})
        if self.path=="/v2/post/publish/video/init/":
            j=json.loads(body); STATE["init"]=j; STATE["size"]=j["source_info"]["video_size"]
            return self._j({"data":{"publish_id":"p123","upload_url":f"http://127.0.0.1:{self.server.server_port}/upload"},**ok})
        if self.path=="/v2/post/publish/status/fetch/":
            done = STATE["bytes"]==STATE["size"]
            print("MOCK STATE", json.dumps({"privacy":STATE["init"]["post_info"]["privacy_level"],"title":STATE["init"]["post_info"]["title"][:60],"size":STATE["size"],"received":STATE["bytes"],"puts":STATE["puts"]}), flush=True)
            return self._j({"data":{"status":"PUBLISH_COMPLETE" if done else "FAILED","fail_reason":"incomplete"},**ok})
    def do_PUT(self):
        n=int(self.headers["Content-Length"]); self.rfile.read(n); STATE["bytes"]+=n; STATE["puts"].append(self.headers["Content-Range"])
        self.send_response(201); self.end_headers()
HTTPServer(("127.0.0.1",int(sys.argv[1])),H).serve_forever()
