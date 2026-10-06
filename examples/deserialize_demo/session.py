"""Benchmark fixture: unsafe deserialisation and weak hashing."""
import hashlib
import pickle


def load_session(blob):
    """Restore a session from a byte blob.

    ``pickle.loads`` on untrusted input allows arbitrary code execution.
    """
    return pickle.loads(blob)


def password_digest(password):
    """Hash a password with MD5, which is unsuitable for credentials."""
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def safe_digest(payload):
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
