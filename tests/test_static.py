import unittest,re,json,tempfile,threading,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from server import App,make_handler,ROOT

class StaticTests(unittest.TestCase):
    def test_ids_and_local_assets(self):
        html=(ROOT/'static/index.html').read_text();js=(ROOT/'static/app.js').read_text()
        ids=re.findall(r'\bid="([^"]+)"',html)
        self.assertEqual(len(ids),len(set(ids)))
        references=set(re.findall(r"\$\('([^']+)'\)",js))
        self.assertFalse(references-set(ids),references-set(ids))
        self.assertNotIn('innerHTML',js)
        with tempfile.TemporaryDirectory() as directory:
            app=App(db=str(Path(directory)/'demo.sqlite3'));server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(app));t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                paths=['/']+re.findall(r'(?:src|href)="(/[^\"]+)"',html)
                for path in paths:
                    with self.subTest(path=path):
                        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}'+path) as r:
                            self.assertEqual(r.status,200);self.assertGreater(len(r.read()),0)
            finally:server.shutdown();server.server_close();t.join()
