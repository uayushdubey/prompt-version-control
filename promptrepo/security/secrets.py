"""
promptrepo/security/secrets.py

Encrypted API key store for PromptVC.

API keys are encrypted with Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
The master key is derived from one of three sources (in priority order):
  1. OS keyring via the `keyring` library (if installed)
  2. PROMPTVC_MASTER_KEY environment variable (32-byte hex or base64)
  3. Auto-generated key stored in ~/.promptrepo_master (user home, not project)

Keys are stored in `.promptrepo/secrets.enc` as a JSON dict encrypted at rest.

CLI usage:
    promptrepo secrets set openai sk-...
    promptrepo secrets get openai
    promptrepo secrets list
    promptrepo secrets delete openai

Python usage:
    from promptrepo.security.secrets import SecretsStore
    store = SecretsStore(root=Path(".promptrepo"))
    store.set("openai", "sk-...")
    key = store.get("openai")  # returns plaintext key or None

Security properties:
  - Keys never written to disk in plaintext
  - Fernet provides authenticated encryption (tampering detected)
  - OS keyring integration avoids master key appearing in env vars
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets as _secrets
import tempfile
from pathlib import Path
from typing import Dict, List, Optional


class SecretsError(Exception):
    """Raised for secrets store errors."""


def _get_master_key() -> bytes:
    """
    Derive master encryption key from available sources.

    Priority:
    1. OS keyring ('promptrepo' service, 'master_key' username)
    2. PROMPTVC_MASTER_KEY environment variable
    3. Auto-generated key persisted in ~/.promptrepo_master

    Returns:
        32-byte key suitable for Fernet (URL-safe base64 encoded 32 bytes).
    """
    # 1. Try OS keyring
    try:
        import keyring
        stored = keyring.get_password("promptrepo", "master_key")
        if stored:
            raw = base64.urlsafe_b64decode(stored.encode())
            if len(raw) == 32:
                return base64.urlsafe_b64encode(raw)
    except Exception:
        pass

    # 2. Try environment variable
    env_key = os.environ.get("PROMPTVC_MASTER_KEY")
    if env_key:
        # Accept hex (64 chars) or base64 (≥44 chars)
        try:
            if len(env_key) == 64:  # hex
                raw = bytes.fromhex(env_key)
            else:
                raw = base64.urlsafe_b64decode(env_key + "==")
            if len(raw) >= 32:
                return base64.urlsafe_b64encode(raw[:32])
        except Exception:
            # Derive from the string using SHA-256
            raw = hashlib.sha256(env_key.encode()).digest()
            return base64.urlsafe_b64encode(raw)

    # 3. Auto-generate and persist in user home
    key_path = Path.home() / ".promptrepo_master"
    if key_path.exists():
        try:
            raw = base64.urlsafe_b64decode(key_path.read_text().strip())
            if len(raw) == 32:
                return base64.urlsafe_b64encode(raw)
        except Exception:
            pass

    # Generate new 32-byte key
    raw = _secrets.token_bytes(32)
    encoded = base64.urlsafe_b64encode(raw)
    try:
        key_path.write_text(encoded.decode())
        key_path.chmod(0o600)
    except Exception:
        pass  # Continue even if we can't persist

    return encoded


def _get_fernet():
    """Return a Fernet instance. Requires `cryptography` package."""
    try:
        from cryptography.fernet import Fernet
        key = _get_master_key()
        return Fernet(key)
    except ImportError:
        raise SecretsError(
            "The 'cryptography' package is required for secrets encryption. "
            "Install it with: pip install promptrepo[secrets]"
        )


class SecretsStore:
    """
    Encrypted secrets store backed by .promptrepo/secrets.enc.

    Thread-safe for single-process use (uses atomic file replacement).
    """

    def __init__(self, root: Path):
        self._path = root / "secrets.enc"
        self._root = root

    def _load(self) -> Dict[str, str]:
        """Load and decrypt the secrets dict."""
        if not self._path.exists():
            return {}
        try:
            f = _get_fernet()
            ciphertext = self._path.read_bytes()
            plaintext = f.decrypt(ciphertext)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as e:
            raise SecretsError(f"Failed to decrypt secrets store: {e}") from e

    def _save(self, data: Dict[str, str]) -> None:
        """Encrypt and atomically write the secrets dict."""
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            f = _get_fernet()
            plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
            ciphertext = f.encrypt(plaintext)

            # Atomic write
            fd, tmp = tempfile.mkstemp(dir=str(self._root), suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(ciphertext)
                    fh.flush()
                    os.fsync(fh.fileno() if hasattr(fh, "fileno") else fd)
                os.replace(tmp, str(self._path))
            except Exception:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
        except SecretsError:
            raise
        except Exception as e:
            raise SecretsError(f"Failed to save secrets store: {e}") from e

    def set(self, service: str, value: str) -> None:
        """
        Store an encrypted secret.

        Args:
            service: Provider/service name (e.g. "openai", "anthropic").
            value: The plaintext secret value (API key, etc.).
        """
        if not service or not service.strip():
            raise ValueError("Service name cannot be empty.")
        if not value:
            raise ValueError("Secret value cannot be empty.")

        data = self._load()
        data[service.strip().lower()] = value
        self._save(data)

    def get(self, service: str) -> Optional[str]:
        """
        Retrieve a decrypted secret.

        Returns None if the service is not stored.
        """
        if not service:
            return None
        data = self._load()
        return data.get(service.strip().lower())

    def delete(self, service: str) -> bool:
        """
        Delete a stored secret.

        Returns True if the secret existed and was deleted, False otherwise.
        """
        if not service:
            return False
        data = self._load()
        key = service.strip().lower()
        if key in data:
            del data[key]
            self._save(data)
            return True
        return False

    def list_services(self) -> List[str]:
        """Return names of stored services (not their values)."""
        try:
            return sorted(self._load().keys())
        except SecretsError:
            return []

    def get_for_provider(self, provider_name: str) -> Optional[str]:
        """
        Get an API key for a provider, checking secrets store first,
        then falling back to environment variables.

        Environment variable names:
            openai      → OPENAI_API_KEY
            anthropic   → ANTHROPIC_API_KEY
            gemini      → GEMINI_API_KEY
            cohere      → COHERE_API_KEY
        """
        # 1. Secrets store
        stored = self.get(provider_name)
        if stored:
            return stored

        # 2. Environment variables
        env_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "cohere": "COHERE_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "groq": "GROQ_API_KEY",
        }
        env_var = env_map.get(provider_name.lower())
        if env_var:
            return os.environ.get(env_var)

        # 3. Generic pattern
        generic = os.environ.get(f"{provider_name.upper()}_API_KEY")
        return generic

    @property
    def is_available(self) -> bool:
        """True if the cryptography package is installed."""
        try:
            from cryptography.fernet import Fernet  # noqa: F401
            return True
        except ImportError:
            return False
