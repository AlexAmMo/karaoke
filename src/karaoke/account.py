"""Share a single USDB login between independent worker processes for one app session."""

from __future__ import annotations

import threading

from .songs import SongError


class SessionExpired(SongError):
    """A private USDB page reported a signed-out session."""


class AccountChanged(SongError):
    def __init__(self):
        super().__init__("La cuenta USDB ha cambiado. Repite la operación.")


class AccountSession:
    def __init__(self):
        self.lock = threading.Lock()
        self.login_lock = threading.Lock()
        self.generation = 0
        self.changing = False
        self.cookies = None
        self.user = ""

    def begin_change(self, pending=False):
        with self.lock:
            self.generation += 1
            self.changing = pending
            self.cookies = None
            self.user = ""
            return self.generation

    def check(self, generation):
        if generation != self.generation:
            raise AccountChanged()

    def authenticate(self, generation, username, password, login):
        # The network call is protected only by the login lock. Clearing an account
        # from the UI doesn't have to wait for a potentially slow HTTPS request.
        with self.login_lock:
            self.check(generation)
            cookies = login(username, password)
            self.check(generation)
            return cookies

    def finish_change(self, generation, username="", cookies=None):
        with self.lock:
            self.check(generation)
            self.user = username
            self.cookies = cookies
            self.changing = False

    def acquire(self, generation, credentials, login, *, expired=None):
        with self.login_lock:
            with self.lock:
                self.check(generation)
                if self.changing:
                    raise SongError("Espera a que termine el cambio de cuenta USDB.")
                # A second expired worker reuses the refresh already completed by
                # the first one, even if both rejected the same previous cookies.
                if self.cookies is not None and self.cookies is not expired:
                    return self.cookies
            account = credentials()
            if not account.get("username") or not account.get("password"):
                raise SongError("Conecta tu cuenta USDB en Ajustes para consultar el catálogo.")
            cookies = login(account["username"], account["password"])
            with self.lock:
                self.check(generation)
                self.user = account["username"]
                self.cookies = cookies
                return cookies
