"""
Helen WiFi - Server-side Encryption Utilities
ECDH key exchange + AES-GCM encryption for E2E and server-side operations.
"""
import os
import base64
import logging

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("BRO.crypto")

# Nonce size for AES-GCM
NONCE_SIZE = 12


def generate_keypair():
    """Generate an ECDH key pair. Returns (private_key, public_key_b64)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return private_key, base64.b64encode(public_bytes).decode()


def derive_shared_key(private_key, peer_public_b64):
    """Derive a shared AES-256 key from ECDH exchange."""
    peer_public_bytes = base64.b64decode(peer_public_b64)
    peer_public_key = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), peer_public_bytes
    )
    shared_key = private_key.exchange(ec.ECDH(), peer_public_key)
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"helen-wifi-e2e",
    ).derive(shared_key)
    return derived


def encrypt(key, plaintext, aad=None):
    """Encrypt plaintext with AES-256-GCM. Returns base64(nonce + ciphertext).

    Args:
        key: 32-byte AES key
        plaintext: string to encrypt
        aad: optional Associated Authenticated Data (e.g. sender+receiver ID)
             for context binding - authenticated but not encrypted.
    """
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    aad_bytes = aad.encode("utf-8") if isinstance(aad, str) else aad
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad_bytes)
    return base64.b64encode(nonce + ct).decode()


def decrypt(key, ciphertext_b64, aad=None):
    """Decrypt base64(nonce + ciphertext) with AES-256-GCM.

    Args:
        key: 32-byte AES key
        ciphertext_b64: base64-encoded nonce+ciphertext
        aad: must match the AAD used during encryption, or decryption fails.
    """
    raw = base64.b64decode(ciphertext_b64)
    nonce = raw[:NONCE_SIZE]
    ct = raw[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    aad_bytes = aad.encode("utf-8") if isinstance(aad, str) else aad
    return aesgcm.decrypt(nonce, ct, aad_bytes).decode("utf-8")


def encrypt_file(key, input_path, output_path, aad=None):
    """Encrypt a file with AES-256-GCM.

    Args:
        key: 32-byte AES key
        input_path: path to plaintext file
        output_path: path to write encrypted file
        aad: optional Associated Authenticated Data for context binding
    """
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    aad_bytes = aad.encode("utf-8") if isinstance(aad, str) else aad
    with open(input_path, "rb") as f:
        data = f.read()
    ct = aesgcm.encrypt(nonce, data, aad_bytes)
    with open(output_path, "wb") as f:
        f.write(nonce + ct)


def decrypt_file(key, input_path, output_path, aad=None):
    """Decrypt a file encrypted with encrypt_file.

    Args:
        key: 32-byte AES key
        input_path: path to encrypted file
        output_path: path to write decrypted file
        aad: must match the AAD used during encryption
    """
    with open(input_path, "rb") as f:
        raw = f.read()
    nonce = raw[:NONCE_SIZE]
    ct = raw[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    aad_bytes = aad.encode("utf-8") if isinstance(aad, str) else aad
    data = aesgcm.decrypt(nonce, ct, aad_bytes)
    with open(output_path, "wb") as f:
        f.write(data)
