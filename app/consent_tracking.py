"""Short-lived, single-use proof of an accepted inquiry; no personal data."""
from http.cookies import SimpleCookie
import secrets
import threading
import time

COOKIE='an_conversion'
PATH='/tracking/receipt'
TTL=120

class Receipts:
    def __init__(self):
        self.pending={}
        self.lock=threading.Lock()

    def issue(self, consent):
        if consent!='yes':
            return {}
        now=time.time()
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if v>now}
            token=secrets.token_hex(24)
            self.pending[token]=now+TTL
        return {'Set-Cookie':f'{COOKIE}={token}; Max-Age={TTL}; Path={PATH}; Secure; HttpOnly; SameSite=Strict'}

    def consume(self, header):
        cookies=SimpleCookie()
        try: cookies.load(header or '')
        except Exception: return None
        token=cookies[COOKIE].value if COOKIE in cookies else ''
        now=time.time()
        with self.lock:
            expiry=self.pending.pop(token,0)
            self.pending={k:v for k,v in self.pending.items() if v>now}
        # Distinct random transaction ID: no inquiry ID or link to a person.
        return secrets.token_hex(16) if expiry>now else None

    @staticmethod
    def clear():
        return {'Set-Cookie':f'{COOKIE}=; Max-Age=0; Path={PATH}; Secure; HttpOnly; SameSite=Strict'}
