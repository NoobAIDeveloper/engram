#!/usr/bin/env python3
"""Extract Twitter/X session cookies (ct0, auth_token) from a local Chromium browser.

Supports Chrome, Brave, and Microsoft Edge on macOS and Linux. Ports the
decryption scheme used by fieldtheory-cli (afar1/fieldtheory-cli) from
TypeScript to Python, keeping the exact PBKDF2 + AES-128-CBC parameters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# ── Browser registry ────────────────────────────────────────────────────────

SALT = b"saltysalt"
KEY_LENGTH = 16
IV = b" " * 16  # 16 bytes of 0x20
MAC_ITERATIONS = 1003
LINUX_ITERATIONS = 1
LINUX_FALLBACK_PASSWORD = b"peanuts"


@dataclass(frozen=True)
class Browser:
    id: str
    display_name: str
    mac_user_data: str  # relative to $HOME
    linux_user_data: str  # relative to $HOME
    # macOS Keychain entries to try (service, account pairs)
    keychain_entries: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    # Linux secret-tool application names to try
    linux_keyring_apps: tuple[str, ...] = ("chrome",)


BROWSERS: tuple[Browser, ...] = (
    Browser(
        id="chrome",
        display_name="Google Chrome",
        mac_user_data="Library/Application Support/Google/Chrome",
        linux_user_data=".config/google-chrome",
        keychain_entries=(
            ("Chrome Safe Storage", "Chrome"),
            ("Chrome Safe Storage", "Google Chrome"),
            ("Google Chrome Safe Storage", "Chrome"),
            ("Google Chrome Safe Storage", "Google Chrome"),
        ),
        linux_keyring_apps=("chrome",),
    ),
    Browser(
        id="brave",
        display_name="Brave",
        mac_user_data="Library/Application Support/BraveSoftware/Brave-Browser",
        linux_user_data=".config/BraveSoftware/Brave-Browser",
        keychain_entries=(
            ("Brave Safe Storage", "Brave"),
            ("Brave Browser Safe Storage", "Brave Browser"),
        ),
        linux_keyring_apps=("brave",),
    ),
    Browser(
        id="edge",
        display_name="Microsoft Edge",
        mac_user_data="Library/Application Support/Microsoft Edge",
        linux_user_data=".config/microsoft-edge",
        keychain_entries=(
            ("Microsoft Edge Safe Storage", "Microsoft Edge"),
            ("Microsoft Edge Safe Storage", "Chromium"),
        ),
        linux_keyring_apps=("microsoft-edge", "chromium", "chrome"),
    ),
)


def _find_browser(browser_id: str) -> Browser:
    for b in BROWSERS:
        if b.id == browser_id:
            return b
    raise ValueError(f"Unknown browser: {browser_id!r}. Known: {[b.id for b in BROWSERS]}")


def _user_data_dir(browser: Browser) -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / browser.mac_user_data
    if sys.platform.startswith("linux"):
        return home / browser.linux_user_data
    raise NotImplementedError(
        f"Unsupported platform: {sys.platform}. Only macOS and Linux are supported."
    )


def _cookie_db_path(browser: Browser, profile: str = "Default") -> Path:
    base = _user_data_dir(browser) / profile
    # Chrome 96+ moved Cookies into a Network subdir.
    network = base / "Network" / "Cookies"
    if network.exists():
        return network
    return base / "Cookies"


def _profiles_with_cookies(browser: Browser) -> list[str]:
    """Profile dir names that have a cookie DB: ``Default`` first, then
    ``Profile N`` in numeric order."""
    root = _user_data_dir(browser)
    names = ["Default"]
    try:
        extra = [p.name for p in root.glob("Profile *") if p.is_dir()]
    except OSError:
        extra = []

    def _order(name: str) -> tuple[int, str]:
        tail = name[len("Profile "):]
        return (int(tail) if tail.isdigit() else sys.maxsize, name)

    names.extend(sorted(extra, key=_order))
    return [n for n in names if _cookie_db_path(browser, n).exists()]


# ── Key derivation ──────────────────────────────────────────────────────────


def _pbkdf2(password: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=KEY_LENGTH,
        salt=SALT,
        iterations=iterations,
    )
    return kdf.derive(password)


class _KeychainTimeout(Exception):
    """Raised when the user doesn't approve the macOS keychain dialog in time."""


def _run(argv: list[str], timeout: float = 5.0, raise_on_timeout: bool = False) -> str | None:
    """Run a subprocess, return stripped stdout or None on any failure.

    If ``raise_on_timeout`` is True, a subprocess.TimeoutExpired is re-raised as
    ``_KeychainTimeout`` so callers can surface a clear user-facing message
    instead of silently falling through.
    """
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        if raise_on_timeout:
            raise _KeychainTimeout(
                f"Timed out after {timeout:.0f}s waiting for the macOS keychain dialog. "
                f"Rerun and approve the prompt — tip: click 'Always Allow' so you won't "
                f"be prompted again."
            )
        return None
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    out = (result.stdout or "").strip()
    return out or None


def _macos_key(browser: Browser, site_label: str = "X") -> bytes:
    for service, account in browser.keychain_entries:
        pw = _run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", account],
            timeout=120.0,
            raise_on_timeout=True,
        )
        if pw:
            return _pbkdf2(pw.encode("utf-8"), MAC_ITERATIONS)
    raise RuntimeError(
        f"Could not read {browser.display_name} Safe Storage password from the macOS Keychain. "
        f"Open the browser profile logged into {site_label} at least once, then retry. "
        f"You may be prompted to allow 'security' to access the keychain entry."
    )


def _linux_keys(browser: Browser) -> tuple[bytes, bytes | None]:
    """Return (v10_key, v11_key_or_none)."""
    v10 = _pbkdf2(LINUX_FALLBACK_PASSWORD, LINUX_ITERATIONS)
    v11: bytes | None = None
    for app in browser.linux_keyring_apps:
        pw = _run(["secret-tool", "lookup", "application", app])
        if pw:
            v11 = _pbkdf2(pw.encode("utf-8"), LINUX_ITERATIONS)
            break
    return v10, v11


# ── Cookie decryption ───────────────────────────────────────────────────────


def _pkcs7_unpad(data: bytes) -> bytes:
    """Strict PKCS7 unpad. Invalid padding means the key was wrong (or the
    ciphertext is corrupt), so raise instead of returning garbage."""
    pad = data[-1] if data else 0
    if not (1 <= pad <= 16) or len(data) < pad or data[-pad:] != bytes([pad]) * pad:
        raise RuntimeError(
            "Cookie decryption produced invalid padding — the browser's Safe "
            "Storage key did not match this cookie."
        )
    return data[:-pad]


def _decrypt_value(
    encrypted: bytes,
    v10_key: bytes,
    v11_key: bytes | None,
    db_version: int,
    host_key: str = "",
) -> str:
    if not encrypted:
        return ""

    prefix = encrypted[:3]
    if prefix not in (b"v10", b"v11"):
        # Unencrypted (older schema) — return as-is.
        return encrypted.decode("utf-8", errors="replace")

    if prefix == b"v11":
        if v11_key is None:
            raise RuntimeError(
                "Cookie uses the GNOME keyring key (v11), but the keyring password "
                "could not be retrieved. Install libsecret-tools (sudo apt-get install "
                "libsecret-tools) and make sure the browser has stored its password there."
            )
        key = v11_key
    else:
        key = v10_key

    ciphertext = encrypted[3:]
    if len(ciphertext) == 0 or len(ciphertext) % 16 != 0:
        raise RuntimeError("Encrypted cookie has invalid ciphertext length.")

    cipher = Cipher(algorithms.AES(key), modes.CBC(IV))
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    plaintext = _pkcs7_unpad(plaintext)

    # Chrome DB version >= 24 (roughly Chrome 130+) prepends SHA256(host_key)
    # to the plaintext. Strip it only when it really is that hash — the meta
    # version alone is not proof (db_version is kept for the signature only).
    if len(plaintext) >= 32 and host_key:
        if plaintext[:32] == hashlib.sha256(host_key.encode("utf-8")).digest():
            plaintext = plaintext[32:]

    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A wrong key (or an unrecognised plaintext layout) lands here.
        raise RuntimeError(
            "Cookie decrypted to bytes that are not valid text — the browser's "
            "Safe Storage key did not match, or the cookie format changed."
        ) from exc


# ── SQLite access ───────────────────────────────────────────────────────────


def _copy_db(src: Path) -> Path:
    """Copy the locked cookie DB (and WAL/SHM siblings) to a temp file."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="twwiki-cookies-"))
    dst = tmp_dir / "Cookies"
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        sib = src.with_name(src.name + suffix)
        if sib.exists():
            shutil.copy2(sib, dst.with_name(dst.name + suffix))
    return dst


def _domains(host_patterns: tuple[str, ...]) -> list[str]:
    """Normalize host patterns to bare domains, preserving order.

    Accepts ``"x.com"``, ``".x.com"`` and the legacy LIKE form ``"%x.com"``.
    """
    out: list[str] = []
    for pat in host_patterns:
        domain = pat.lstrip("%").lstrip(".").lower()
        if domain and domain not in out:
            out.append(domain)
    return out


def _query_cookies(
    db_path: Path,
    host_patterns: tuple[str, ...] = ("x.com", "twitter.com"),
) -> tuple[list[tuple[str, bytes, str]], int]:
    """Return (rows, db_version). rows is list of (name, encrypted_value,
    host_key), ordered so earlier-listed domains come first.

    host_patterns: domains matched EXACTLY against cookies.host_key — only
    ``<domain>`` and ``.<domain>`` match (never ``netflix.com`` for
    ``x.com``, and never a subdomain, whose cookies the browser would not
    send to the bare domain either). Defaults to the X/Twitter hosts.
    """
    domains = _domains(host_patterns)
    rank: dict[str, int] = {}
    for idx, domain in enumerate(domains):
        rank[domain] = idx
        rank["." + domain] = idx
    if not rank:
        return [], 0

    tmp_db = _copy_db(db_path)
    try:
        conn = sqlite3.connect(str(tmp_db))
        try:
            clause = ", ".join(["?"] * len(rank))
            cur = conn.execute(
                "SELECT name, encrypted_value, host_key FROM cookies "
                f"WHERE lower(host_key) IN ({clause})",
                tuple(rank),
            )
            rows = [
                (r[0], bytes(r[1]) if r[1] is not None else b"", r[2] or "")
                for r in cur.fetchall()
            ]
            # First-listed domain wins when a name exists on several hosts.
            rows.sort(key=lambda r: rank.get(r[2].lower(), len(rank)))
            db_version = 0
            try:
                vrow = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
                if vrow and vrow[0] is not None:
                    db_version = int(vrow[0])
            except (sqlite3.Error, ValueError):
                db_version = 0
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp_db.parent, ignore_errors=True)

    return rows, db_version


# ── Public API ──────────────────────────────────────────────────────────────


def list_available_browsers() -> list[str]:
    """Return browser ids with a cookie DB on disk (in any profile)."""
    available: list[str] = []
    for browser in BROWSERS:
        try:
            if _profiles_with_cookies(browser):
                available.append(browser.id)
        except NotImplementedError:
            return []
    return available


def extract_twitter_cookies(browser: str = "auto") -> dict[str, str]:
    """Return ``{'ct0': ..., 'auth_token': ...}`` for the logged-in X session.

    ``browser='auto'`` picks the first installed Chromium-family browser whose
    extraction succeeds. Pass an explicit id ('chrome', 'brave', 'edge') to
    force a specific browser.

    Raises ``NotImplementedError`` on Windows, ``FileNotFoundError`` if no
    supported browser is installed, and ``RuntimeError`` with a clear message
    for missing cookies, a locked DB that could not be copied, or decryption
    failures.
    """
    if sys.platform == "win32":
        raise NotImplementedError(
            "Windows is not supported in this version. "
            "Run this on macOS or Linux, or export cookies manually."
        )
    if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
        raise NotImplementedError(f"Unsupported platform: {sys.platform}")

    if browser == "auto":
        candidates = list_available_browsers()
        if not candidates:
            raise FileNotFoundError(
                "No supported browser found. Looked for cookie DBs from: "
                + ", ".join(b.display_name for b in BROWSERS)
                + ". Install one of these browsers and log into X, then retry."
            )
        last_error: Exception | None = None
        for bid in candidates:
            try:
                return _extract_for(_find_browser(bid))
            except _KeychainTimeout:
                raise
            except (RuntimeError, FileNotFoundError) as exc:
                last_error = exc
                print(
                    f"[cookies] {bid}: {exc}. Trying next browser...",
                    file=sys.stderr,
                )
        assert last_error is not None
        raise RuntimeError(
            f"Tried browsers {candidates} but none yielded usable X cookies. "
            f"Last error: {last_error}"
        )

    return _extract_for(_find_browser(browser))


def extract_cookies(
    host_patterns: tuple[str, ...],
    wanted_names: set[str],
    *,
    optional_names: set[str] | None = None,
    browser: str = "auto",
    site_label: str = "",
) -> dict[str, str]:
    """Generic cookie extractor. Same semantics as extract_twitter_cookies
    but parameterized on which hosts and cookie names we care about.

    host_patterns are domains matched exactly against cookies.host_key
    (``chatgpt.com`` matches ``chatgpt.com`` and ``.chatgpt.com`` only),
    e.g. ``("chatgpt.com", "chat.openai.com")``. When the same cookie name
    exists for several of them, the first-listed domain wins.

    ``wanted_names`` must all be found or we raise. ``optional_names``
    are returned if present but never required — use this for
    Cloudflare cookies (cf_clearance, __cf_bm) where absence just means
    the user hasn't visited the site recently.
    """
    if sys.platform == "win32":
        raise NotImplementedError(
            "Windows is not supported. Run on macOS or Linux."
        )
    if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
        raise NotImplementedError(f"Unsupported platform: {sys.platform}")

    label = site_label or ", ".join(_domains(host_patterns))

    if browser == "auto":
        candidates = list_available_browsers()
        if not candidates:
            raise FileNotFoundError(
                "No supported browser found. Install Chrome, Brave, or Edge and retry."
            )
        last_error: Exception | None = None
        for bid in candidates:
            try:
                return _extract_for(
                    _find_browser(bid),
                    host_patterns=host_patterns,
                    wanted_names=wanted_names,
                    optional_names=optional_names,
                    site_label=label,
                )
            except _KeychainTimeout:
                raise
            except (RuntimeError, FileNotFoundError) as exc:
                last_error = exc
                print(f"[cookies] {bid}: {exc}. Trying next browser...", file=sys.stderr)
        assert last_error is not None
        raise RuntimeError(
            f"Tried browsers {candidates} but none yielded cookies for {label}. "
            f"Last error: {last_error}"
        )

    return _extract_for(
        _find_browser(browser),
        host_patterns=host_patterns,
        wanted_names=wanted_names,
        optional_names=optional_names,
        site_label=label,
    )


def _extract_for(
    browser: Browser,
    *,
    host_patterns: tuple[str, ...] = ("x.com", "twitter.com"),
    wanted_names: set[str] | None = None,
    optional_names: set[str] | None = None,
    site_label: str = "x.com / twitter.com",
) -> dict[str, str]:
    profiles = _profiles_with_cookies(browser)
    if not profiles:
        raise FileNotFoundError(
            f"{browser.display_name} Cookies DB not found at {_cookie_db_path(browser)} "
            f"(nor in any 'Profile N' directory). Install the browser and open it "
            f"at least once."
        )

    if sys.platform == "darwin":
        v10_key = _macos_key(browser, site_label)
        v11_key: bytes | None = None
    else:
        v10_key, v11_key = _linux_keys(browser)

    # Default first, then Profile N: the first profile that actually holds the
    # required cookies wins.
    errors: list[tuple[str, RuntimeError]] = []
    for profile in profiles:
        try:
            return _extract_from_profile(
                browser,
                profile,
                v10_key,
                v11_key,
                host_patterns=host_patterns,
                wanted_names=wanted_names,
                optional_names=optional_names,
                site_label=site_label,
            )
        except RuntimeError as exc:
            errors.append((profile, exc))
    if len(errors) == 1:
        raise errors[0][1]
    raise RuntimeError(
        f"No {browser.display_name} profile yielded cookies for {site_label}: "
        + " | ".join(f"[{profile}] {exc}" for profile, exc in errors)
    )


def _extract_from_profile(
    browser: Browser,
    profile: str,
    v10_key: bytes,
    v11_key: bytes | None,
    *,
    host_patterns: tuple[str, ...],
    wanted_names: set[str] | None,
    optional_names: set[str] | None,
    site_label: str,
) -> dict[str, str]:
    db_path = _cookie_db_path(browser, profile)
    try:
        rows, db_version = _query_cookies(db_path, host_patterns=host_patterns)
    except (sqlite3.Error, OSError) as exc:
        raise RuntimeError(
            f"Could not read {browser.display_name} cookie DB at {db_path}: {exc}. "
            f"If the browser is running, close it and retry."
        ) from exc

    wanted = wanted_names if wanted_names is not None else {"ct0", "auth_token"}
    optional = optional_names or set()
    interesting = wanted | optional
    results: dict[str, str] = {}
    # rows are ordered by domain preference; the first non-empty value wins.
    for name, encrypted, host_key in rows:
        if name not in interesting or name in results:
            continue
        try:
            value = _decrypt_value(encrypted, v10_key, v11_key, db_version, host_key)
        except Exception as exc:  # noqa: BLE001 - surface as RuntimeError
            raise RuntimeError(
                f"Decryption failed for cookie {name!r} ({host_key}) in "
                f"{browser.display_name} profile {profile!r}: {exc} "
                f"If the browser was just updated, this may be a Chrome version "
                f"mismatch — please file a bug."
            ) from exc
        value = value.rstrip("\x00").strip()
        if value:
            results[name] = value

    missing = wanted - results.keys()
    if missing:
        raise RuntimeError(
            f"Found cookies in {browser.display_name} (profile {profile!r}) but "
            f"missing {sorted(missing)} for {site_label}. You are probably not "
            f"logged into that site in this browser — open {browser.display_name}, "
            f"log into it, and retry."
        )
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract X/Twitter cookies from a Chromium browser.")
    parser.add_argument(
        "--browser",
        default="auto",
        help="Browser id: auto (default), chrome, brave, or edge.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List installed browsers and exit.",
    )
    args = parser.parse_args(argv)

    if args.list:
        print(json.dumps(list_available_browsers()))
        return 0

    try:
        cookies = extract_twitter_cookies(args.browser)
    except NotImplementedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except _KeychainTimeout as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(cookies))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
