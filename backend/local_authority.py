"""Loopback, same-origin capability for explicitly synthetic local operations controls.

This is not production identity or an enterprise operator authorization system.
The server chooses the actor/role; request bodies cannot promote agent recommendations
into operator authority. Every state-changing route also enforces its dataset fence.
"""
import ipaddress
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

TOKEN_HEADER="X-Operations-Token"


def _loopback(host):
    if host=="localhost":return True
    try:return ipaddress.ip_address(host).is_loopback
    except ValueError:return False


class LocalOperationsAuthority:
    def __init__(self):
        self._token=secrets.token_urlsafe(32)

    def _fence(self,request: Request):
        if not request.client or not _loopback(request.client.host) or not _loopback(request.url.hostname):
            raise HTTPException(403,"Operations controls require a local connection")
        origin=request.headers.get("origin")
        if origin:
            parsed=urlsplit(origin)
            try:
                origin_port=parsed.port or (443 if parsed.scheme=="https" else 80)
                request_port=request.url.port or (443 if request.url.scheme=="https" else 80)
            except ValueError:
                raise HTTPException(403,"Invalid operations origin") from None
            if (parsed.scheme!=request.url.scheme or parsed.hostname!=request.url.hostname
                    or origin_port!=request_port or parsed.username or parsed.password or parsed.path not in ("","/")):
                raise HTTPException(403,"Operations controls require the same origin")

    @staticmethod
    def operator_id():
        """The configured local operator (SUHAIL_OPERATOR_IDS, first entry; default DEMO-OPERATOR-LOCAL)."""
        from operations.lifecycle import operator_ids
        return operator_ids()[0]

    def session(self,request: Request):
        self._fence(request)
        actor=self.operator_id()
        return {"token":self._token,"mode":"synthetic_local_operations","synthetic":True,
                "actor_id":"SYN-"+actor.removeprefix("DEMO-"),"role":"operator",
                "scope":["triage_control","simulation_control","operator_decision","outcome_verification"],
                "production_authority":False}

    def authorize(self,request: Request):
        self._fence(request)
        token=request.headers.get(TOKEN_HEADER,"")
        if len(token)>128 or not secrets.compare_digest(token,self._token):
            raise HTTPException(403,"A local operations session is required")
        return {"actor_id":self.operator_id(),"role":"operator",
                "authority":"LOCAL_DEMO_OPERATOR","synthetic":True}
