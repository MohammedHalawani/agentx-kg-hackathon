"""Local control fence tests; no DB, credentials, provider or sockets."""
from pathlib import Path
import sys
import unittest

from fastapi import FastAPI,Request
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.local_authority import LocalDemoAuthority


class LocalAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.authority=LocalDemoAuthority()
        self.app=FastAPI()
        @self.app.get("/session")
        def session(request: Request):return self.authority.session(request)
        @self.app.post("/control")
        def control(request: Request):return self.authority.authorize(request)

    def client(self,peer="127.0.0.1",base="http://127.0.0.1"):
        return TestClient(self.app,base_url=base,client=(peer,12345))

    def test_server_actor_with_nonce_required(self):
        client=self.client()
        self.assertEqual(client.post("/control").status_code,403)
        session=client.get("/session").json()
        response=client.post("/control",headers={"X-Operations-Token":session["token"]})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["role"],"demo_operator")
        self.assertFalse(session["production_authority"])

    def test_remote_peer_host_and_origin_are_refused(self):
        for peer,base in (("192.0.2.4","http://127.0.0.1"),("127.0.0.1","http://attacker.test")):
            self.assertEqual(self.client(peer,base).get("/session").status_code,403)
        client=self.client()
        token=client.get("/session").json()["token"]
        for origin in ("https://attacker.test","http://127.0.0.1:9999","null"):
            self.assertEqual(client.post("/control",headers={"X-Operations-Token":token,"Origin":origin}).status_code,403)
        self.assertEqual(client.post("/control",headers={"X-Operations-Token":token,"Origin":"http://127.0.0.1"}).status_code,200)

    def test_restart_revokes_token_and_client_cannot_choose_actor(self):
        client=self.client()
        token=client.get("/session").json()["token"]
        self.authority._token=LocalDemoAuthority()._token
        self.assertEqual(client.post("/control",headers={"X-Operations-Token":token}).status_code,403)
        token=client.get("/session").json()["token"]
        response=client.post("/control",json={"actor_id":"agent","role":"administrator"},headers={"X-Operations-Token":token})
        self.assertEqual(response.json()["actor_id"],"DEMO-OPERATOR-LOCAL")


if __name__=="__main__":unittest.main()
