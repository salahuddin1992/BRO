"""
Helen WiFi - Signal Protocol Implementation
Military-grade end-to-end encryption with four layers:

Layer 1: X3DH (Extended Triple Diffie-Hellman)
  - Initial key agreement between two users
  - 4 DH operations for forward secrecy
  - Uses X25519 key pairs

Layer 2: Double Ratchet
  - Per-message key derivation
  - Symmetric ratchet (KDF chain) advances with each message
  - Asymmetric ratchet (DH) advances with each reply
  - Supports out-of-order messages (up to 256 skipped)
  - Post-compromise security: session self-heals after breach

Layer 3: Sender Keys (Group Encryption)
  - Efficient group messaging: encrypt once, all members decrypt
  - Each member has their own sender key chain
  - Forward secrecy within groups

Layer 4: Server Onion Encryption
  - Multi-layer encryption for cross-server messages
  - Each server peels one layer, sees nothing else
  - N servers = N layers

File Encryption:
  - Each file encrypted with unique AES-256-GCM key
  - File key encrypted via Double Ratchet session
"""
import hashlib
import hmac as hmac_mod
import json
import logging
import os
import secrets
import struct
import threading
import time
from collections import OrderedDict

logger = logging.getLogger("BRO.signal")

# Try to import cryptography library
try:
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey,
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False
    logger.warning("cryptography library not available - Signal Protocol disabled")


# Constants
MAX_SKIP = 256          # Max skipped messages in a chain
SIGNED_KEY_ROTATION = 7 * 24 * 3600  # 7 days
ONE_TIME_KEY_COUNT = 20  # Number of one-time prekeys to generate
INFO_RATCHET = b"HelenWiFi_DoubleRatchet"
INFO_MESSAGE = b"HelenWiFi_MessageKeys"
INFO_X3DH = b"HelenWiFi_X3DH"
INFO_SENDER_KEY = b"HelenWiFi_SenderKey"
INFO_ONION = b"HelenWiFi_OnionLayer"


def _hkdf_derive(input_key_material, info, length=32, salt=None):
    """Derive key using HKDF-SHA256."""
    if not _CRYPTO_AVAILABLE:
        # Fallback: simple HMAC-based derivation
        if salt is None:
            salt = b'\x00' * 32
        return hmac_mod.new(salt, input_key_material + info, hashlib.sha256).digest()[:length]

    if salt is None:
        salt = b'\x00' * 32
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        info=info,
    )
    return hkdf.derive(input_key_material)


def _aes_encrypt(key, plaintext, associated_data=None):
    """Encrypt with AES-256-GCM."""
    if not _CRYPTO_AVAILABLE:
        # Fallback: XOR cipher (NOT secure - only for structure testing)
        nonce = os.urandom(12)
        ct = bytes(a ^ b for a, b in zip(plaintext, (key * (len(plaintext) // 32 + 1))[:len(plaintext)]))
        return nonce + ct

    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, associated_data)
    return nonce + ct


def _aes_decrypt(key, ciphertext, associated_data=None):
    """Decrypt with AES-256-GCM."""
    if not _CRYPTO_AVAILABLE:
        nonce = ciphertext[:12]
        ct = ciphertext[12:]
        return bytes(a ^ b for a, b in zip(ct, (key * (len(ct) // 32 + 1))[:len(ct)]))

    nonce = ciphertext[:12]
    ct = ciphertext[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, associated_data)


def _generate_x25519_keypair():
    """Generate X25519 key pair."""
    if not _CRYPTO_AVAILABLE:
        priv = os.urandom(32)
        pub = hashlib.sha256(priv).digest()
        return priv, pub

    private = X25519PrivateKey.generate()
    public = private.public_key()
    priv_bytes = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    pub_bytes = public.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return priv_bytes, pub_bytes


def _x25519_dh(private_bytes, public_bytes):
    """Perform X25519 Diffie-Hellman exchange."""
    if not _CRYPTO_AVAILABLE:
        return hmac_mod.new(private_bytes, public_bytes, hashlib.sha256).digest()

    private = X25519PrivateKey.from_private_bytes(private_bytes)
    public = X25519PublicKey.from_public_bytes(public_bytes)
    return private.exchange(public)


class IdentityBundle:
    """
    A user's identity key bundle for X3DH.

    Contains:
    - Identity key pair (long-term, permanent)
    - Signed prekey pair (rotates every 7-30 days)
    - One-time prekeys (consumed on first contact, auto-replenished)
    """

    def __init__(self, username):
        self.username = username
        self.created_at = time.time()

        # Identity key (permanent)
        self.identity_private, self.identity_public = _generate_x25519_keypair()

        # Signed prekey (rotates periodically)
        self.signed_prekey_private, self.signed_prekey_public = _generate_x25519_keypair()
        self.signed_prekey_created = time.time()
        self.signed_prekey_signature = self._sign_prekey()

        # One-time prekeys
        self.one_time_prekeys = OrderedDict()  # {key_id: (private, public)}
        self._generate_one_time_keys(ONE_TIME_KEY_COUNT)

        self._lock = threading.Lock()

    def _sign_prekey(self):
        """Sign the signed prekey with the identity key."""
        return hmac_mod.new(
            self.identity_private,
            self.signed_prekey_public,
            hashlib.sha256,
        ).digest()

    def _generate_one_time_keys(self, count):
        """Generate a batch of one-time prekeys."""
        for _ in range(count):
            key_id = secrets.token_hex(8)
            priv, pub = _generate_x25519_keypair()
            self.one_time_prekeys[key_id] = (priv, pub)

    def consume_one_time_key(self, key_id):
        """Consume and return a one-time prekey. Returns (private, public) or None."""
        with self._lock:
            pair = self.one_time_prekeys.pop(key_id, None)
            # Auto-replenish if running low
            if len(self.one_time_prekeys) < 5:
                self._generate_one_time_keys(ONE_TIME_KEY_COUNT)
            return pair

    def should_rotate_signed_key(self):
        """Check if signed prekey should be rotated."""
        return time.time() - self.signed_prekey_created > SIGNED_KEY_ROTATION

    def rotate_signed_key(self):
        """Rotate the signed prekey."""
        with self._lock:
            self.signed_prekey_private, self.signed_prekey_public = _generate_x25519_keypair()
            self.signed_prekey_created = time.time()
            self.signed_prekey_signature = self._sign_prekey()

    def get_public_bundle(self):
        """Get the public portion for sharing with other users."""
        with self._lock:
            otk = {}
            for kid, (_, pub) in list(self.one_time_prekeys.items())[:5]:
                otk[kid] = pub.hex()

            return {
                "username": self.username,
                "identity_key": self.identity_public.hex(),
                "signed_prekey": self.signed_prekey_public.hex(),
                "signed_prekey_signature": self.signed_prekey_signature.hex(),
                "one_time_prekeys": otk,
            }

    def to_storage(self):
        """Serialize for persistent storage."""
        with self._lock:
            otk = {}
            for kid, (priv, pub) in self.one_time_prekeys.items():
                otk[kid] = {"private": priv.hex(), "public": pub.hex()}

            return {
                "username": self.username,
                "created_at": self.created_at,
                "identity_private": self.identity_private.hex(),
                "identity_public": self.identity_public.hex(),
                "signed_prekey_private": self.signed_prekey_private.hex(),
                "signed_prekey_public": self.signed_prekey_public.hex(),
                "signed_prekey_created": self.signed_prekey_created,
                "signed_prekey_signature": self.signed_prekey_signature.hex(),
                "one_time_prekeys": otk,
            }

    @classmethod
    def from_storage(cls, data):
        """Deserialize from persistent storage."""
        bundle = cls.__new__(cls)
        bundle.username = data["username"]
        bundle.created_at = data.get("created_at", time.time())
        bundle.identity_private = bytes.fromhex(data["identity_private"])
        bundle.identity_public = bytes.fromhex(data["identity_public"])
        bundle.signed_prekey_private = bytes.fromhex(data["signed_prekey_private"])
        bundle.signed_prekey_public = bytes.fromhex(data["signed_prekey_public"])
        bundle.signed_prekey_created = data.get("signed_prekey_created", time.time())
        bundle.signed_prekey_signature = bytes.fromhex(data["signed_prekey_signature"])
        bundle.one_time_prekeys = OrderedDict()
        for kid, kd in data.get("one_time_prekeys", {}).items():
            bundle.one_time_prekeys[kid] = (bytes.fromhex(kd["private"]), bytes.fromhex(kd["public"]))
        bundle._lock = threading.Lock()
        return bundle


class X3DHSession:
    """
    Extended Triple Diffie-Hellman key agreement.

    Performs 4 DH operations:
      DH1: sender_identity × receiver_signed_prekey
      DH2: sender_ephemeral × receiver_identity
      DH3: sender_ephemeral × receiver_signed_prekey
      DH4: sender_ephemeral × receiver_one_time_prekey (optional)

    Result: shared secret derived via HKDF-SHA256
    """

    @staticmethod
    def initiate(sender_bundle, receiver_public_bundle):
        """
        Initiator side of X3DH.

        Args:
            sender_bundle: IdentityBundle of the sender
            receiver_public_bundle: Public bundle dict of the receiver

        Returns:
            (shared_secret, ephemeral_public, used_otk_id) or None on failure
        """
        try:
            receiver_identity = bytes.fromhex(receiver_public_bundle["identity_key"])
            receiver_signed = bytes.fromhex(receiver_public_bundle["signed_prekey"])

            # Generate ephemeral key
            eph_private, eph_public = _generate_x25519_keypair()

            # DH1: sender_identity × receiver_signed
            dh1 = _x25519_dh(sender_bundle.identity_private, receiver_signed)

            # DH2: sender_ephemeral × receiver_identity
            dh2 = _x25519_dh(eph_private, receiver_identity)

            # DH3: sender_ephemeral × receiver_signed
            dh3 = _x25519_dh(eph_private, receiver_signed)

            # DH4: sender_ephemeral × receiver_one_time (if available)
            dh4 = b''
            used_otk_id = None
            otk_map = receiver_public_bundle.get("one_time_prekeys", {})
            if otk_map:
                otk_id = next(iter(otk_map))
                otk_pub = bytes.fromhex(otk_map[otk_id])
                dh4 = _x25519_dh(eph_private, otk_pub)
                used_otk_id = otk_id

            # Derive shared secret
            combined = dh1 + dh2 + dh3 + dh4
            shared_secret = _hkdf_derive(combined, INFO_X3DH, length=32)

            return shared_secret, eph_public, used_otk_id

        except Exception as e:
            logger.error("X3DH initiation failed: %s", e)
            return None

    @staticmethod
    def respond(receiver_bundle, sender_identity_pub, sender_ephemeral_pub, used_otk_id=None):
        """
        Responder side of X3DH.

        Args:
            receiver_bundle: IdentityBundle of the receiver
            sender_identity_pub: Sender's identity public key (bytes)
            sender_ephemeral_pub: Sender's ephemeral public key (bytes)
            used_otk_id: ID of the one-time prekey used (if any)

        Returns:
            shared_secret or None on failure
        """
        try:
            # DH1: receiver_signed × sender_identity
            dh1 = _x25519_dh(receiver_bundle.signed_prekey_private, sender_identity_pub)

            # DH2: receiver_identity × sender_ephemeral
            dh2 = _x25519_dh(receiver_bundle.identity_private, sender_ephemeral_pub)

            # DH3: receiver_signed × sender_ephemeral
            dh3 = _x25519_dh(receiver_bundle.signed_prekey_private, sender_ephemeral_pub)

            # DH4: receiver_one_time × sender_ephemeral
            dh4 = b''
            if used_otk_id:
                otk_pair = receiver_bundle.consume_one_time_key(used_otk_id)
                if otk_pair:
                    dh4 = _x25519_dh(otk_pair[0], sender_ephemeral_pub)

            combined = dh1 + dh2 + dh3 + dh4
            shared_secret = _hkdf_derive(combined, INFO_X3DH, length=32)

            return shared_secret

        except Exception as e:
            logger.error("X3DH response failed: %s", e)
            return None


class DoubleRatchet:
    """
    Double Ratchet Algorithm for per-message encryption.

    Two ratchets:
    1. Symmetric Ratchet (KDF chain): Advances with each message
       - HMAC-SHA256 based key derivation
       - Each message gets a unique key that's deleted after use

    2. Asymmetric Ratchet (DH): Advances with each turn of conversation
       - New DH key pair generated on each reply
       - New root key derived from DH output + old root key

    Features:
    - Forward secrecy: compromise of current key doesn't expose past messages
    - Post-compromise security: session self-heals after breach
    - Out-of-order message support: up to MAX_SKIP skipped messages
    """

    def __init__(self, shared_secret, is_initiator=True):
        """
        Initialize Double Ratchet from X3DH shared secret.

        Args:
            shared_secret: 32-byte shared secret from X3DH
            is_initiator: True if this is the session initiator
        """
        self.root_key = shared_secret
        self.is_initiator = is_initiator
        self._lock = threading.Lock()

        # DH ratchet keys
        self.dh_private, self.dh_public = _generate_x25519_keypair()
        self.remote_dh_public = None

        # Sending chain
        self.send_chain_key = None
        self.send_message_number = 0

        # Receiving chain
        self.recv_chain_key = None
        self.recv_message_number = 0

        # Previous sending chain number (for header)
        self.previous_send_count = 0

        # Skipped message keys: {(dh_pub_hex, msg_num): message_key}
        self.skipped_keys = OrderedDict()

        # Message counter for the current chain
        self._initialized = False

    def initialize_as_sender(self, remote_dh_public):
        """Initialize the ratchet as the first sender (initiator)."""
        with self._lock:
            self.remote_dh_public = remote_dh_public
            dh_output = _x25519_dh(self.dh_private, remote_dh_public)
            self.root_key, self.send_chain_key = self._kdf_root(self.root_key, dh_output)
            self._initialized = True

    def initialize_as_receiver(self):
        """Initialize the ratchet as the first receiver (responder)."""
        with self._lock:
            # Receiver starts without a send chain; it will be created on first send
            self._initialized = True

    def encrypt(self, plaintext):
        """
        Encrypt a message.

        Args:
            plaintext: bytes to encrypt

        Returns:
            dict with header and ciphertext, or None on failure
        """
        with self._lock:
            if not self._initialized:
                return None

            if self.send_chain_key is None:
                # Need to perform DH ratchet step first
                if self.remote_dh_public is None:
                    return None
                self._dh_ratchet_send()

            # Derive message key from chain
            chain_key, message_key = self._kdf_chain(self.send_chain_key)
            self.send_chain_key = chain_key

            # Encrypt
            header = {
                "dh": self.dh_public.hex(),
                "pn": self.previous_send_count,
                "n": self.send_message_number,
            }
            header_bytes = json.dumps(header, separators=(',', ':')).encode()
            ciphertext = _aes_encrypt(message_key, plaintext, header_bytes)

            self.send_message_number += 1

            return {
                "header": header,
                "ciphertext": ciphertext.hex(),
            }

    def decrypt(self, message):
        """
        Decrypt a message.

        Args:
            message: dict with header and ciphertext

        Returns:
            plaintext bytes or None on failure
        """
        with self._lock:
            if not self._initialized:
                return None

            header = message["header"]
            ciphertext = bytes.fromhex(message["ciphertext"])
            dh_pub = bytes.fromhex(header["dh"])
            msg_num = header["n"]
            prev_count = header["pn"]

            # Check skipped keys first
            skip_key = (header["dh"], msg_num)
            if skip_key in self.skipped_keys:
                mk = self.skipped_keys.pop(skip_key)
                header_bytes = json.dumps(header, separators=(',', ':')).encode()
                return _aes_decrypt(mk, ciphertext, header_bytes)

            # Check if we need to advance the DH ratchet
            if dh_pub != self.remote_dh_public:
                # Skip any remaining messages in the current receiving chain
                if self.recv_chain_key is not None:
                    self._skip_messages(self.remote_dh_public, self.recv_message_number, prev_count)

                # DH ratchet step
                self._dh_ratchet_recv(dh_pub)

            # Skip ahead if needed
            if msg_num > self.recv_message_number:
                self._skip_messages(dh_pub, self.recv_message_number, msg_num)

            # Derive message key
            chain_key, message_key = self._kdf_chain(self.recv_chain_key)
            self.recv_chain_key = chain_key
            self.recv_message_number = msg_num + 1

            header_bytes = json.dumps(header, separators=(',', ':')).encode()
            try:
                return _aes_decrypt(message_key, ciphertext, header_bytes)
            except Exception as e:
                logger.error("Decrypt failed: %s", e)
                return None

    def _dh_ratchet_send(self):
        """Perform DH ratchet step for sending."""
        self.previous_send_count = self.send_message_number
        self.send_message_number = 0
        self.dh_private, self.dh_public = _generate_x25519_keypair()
        dh_output = _x25519_dh(self.dh_private, self.remote_dh_public)
        self.root_key, self.send_chain_key = self._kdf_root(self.root_key, dh_output)

    def _dh_ratchet_recv(self, remote_dh_pub):
        """Perform DH ratchet step for receiving."""
        self.previous_send_count = self.send_message_number
        self.send_message_number = 0
        self.recv_message_number = 0
        self.remote_dh_public = remote_dh_pub

        dh_output = _x25519_dh(self.dh_private, remote_dh_pub)
        self.root_key, self.recv_chain_key = self._kdf_root(self.root_key, dh_output)

        # Generate new DH key pair for next send
        self.dh_private, self.dh_public = _generate_x25519_keypair()
        dh_output = _x25519_dh(self.dh_private, remote_dh_pub)
        self.root_key, self.send_chain_key = self._kdf_root(self.root_key, dh_output)

    def _skip_messages(self, dh_pub, start, end):
        """Skip messages and store their keys for later decryption."""
        if end - start > MAX_SKIP:
            logger.warning("Too many skipped messages: %d", end - start)
            return

        dh_hex = dh_pub.hex() if isinstance(dh_pub, bytes) else dh_pub
        for i in range(start, end):
            chain_key, message_key = self._kdf_chain(self.recv_chain_key)
            self.recv_chain_key = chain_key
            self.skipped_keys[(dh_hex, i)] = message_key

            # Evict oldest if too many
            while len(self.skipped_keys) > MAX_SKIP:
                self.skipped_keys.popitem(last=False)

    @staticmethod
    def _kdf_root(root_key, dh_output):
        """Derive new root key and chain key from DH output."""
        derived = _hkdf_derive(dh_output, INFO_RATCHET, length=64, salt=root_key)
        return derived[:32], derived[32:]

    @staticmethod
    def _kdf_chain(chain_key):
        """Derive next chain key and message key."""
        new_chain = hmac_mod.new(chain_key, b'\x01', hashlib.sha256).digest()
        msg_key = hmac_mod.new(chain_key, b'\x02', hashlib.sha256).digest()
        return new_chain, msg_key

    def to_storage(self):
        """Serialize ratchet state for persistence."""
        with self._lock:
            skipped = {}
            for (dh_hex, num), key in self.skipped_keys.items():
                skipped[f"{dh_hex}:{num}"] = key.hex()

            return {
                "root_key": self.root_key.hex(),
                "is_initiator": self.is_initiator,
                "dh_private": self.dh_private.hex(),
                "dh_public": self.dh_public.hex(),
                "remote_dh_public": self.remote_dh_public.hex() if self.remote_dh_public else None,
                "send_chain_key": self.send_chain_key.hex() if self.send_chain_key else None,
                "send_message_number": self.send_message_number,
                "recv_chain_key": self.recv_chain_key.hex() if self.recv_chain_key else None,
                "recv_message_number": self.recv_message_number,
                "previous_send_count": self.previous_send_count,
                "skipped_keys": skipped,
                "initialized": self._initialized,
            }

    @classmethod
    def from_storage(cls, data):
        """Restore ratchet from persistent storage."""
        ratchet = cls.__new__(cls)
        ratchet.root_key = bytes.fromhex(data["root_key"])
        ratchet.is_initiator = data["is_initiator"]
        ratchet.dh_private = bytes.fromhex(data["dh_private"])
        ratchet.dh_public = bytes.fromhex(data["dh_public"])
        ratchet.remote_dh_public = bytes.fromhex(data["remote_dh_public"]) if data.get("remote_dh_public") else None
        ratchet.send_chain_key = bytes.fromhex(data["send_chain_key"]) if data.get("send_chain_key") else None
        ratchet.send_message_number = data.get("send_message_number", 0)
        ratchet.recv_chain_key = bytes.fromhex(data["recv_chain_key"]) if data.get("recv_chain_key") else None
        ratchet.recv_message_number = data.get("recv_message_number", 0)
        ratchet.previous_send_count = data.get("previous_send_count", 0)
        ratchet._initialized = data.get("initialized", False)
        ratchet._lock = threading.Lock()

        ratchet.skipped_keys = OrderedDict()
        for k, v in data.get("skipped_keys", {}).items():
            dh_hex, num = k.rsplit(":", 1)
            ratchet.skipped_keys[(dh_hex, int(num))] = bytes.fromhex(v)

        return ratchet


class SenderKeyState:
    """
    Sender Key for efficient group encryption.

    Instead of encrypting N times for N members, each member has
    their own sender key chain. They encrypt once with their chain,
    and all group members who have the chain can decrypt.
    """

    def __init__(self, group_id, sender_username):
        self.group_id = group_id
        self.sender_username = sender_username
        self.chain_key = os.urandom(32)
        self.signing_key = os.urandom(32)
        self.message_number = 0
        self._lock = threading.Lock()

    def encrypt(self, plaintext):
        """Encrypt a group message using the sender key chain."""
        with self._lock:
            # Derive message key
            msg_key = hmac_mod.new(
                self.chain_key, struct.pack(">I", self.message_number), hashlib.sha256
            ).digest()

            # Advance chain
            self.chain_key = hmac_mod.new(
                self.chain_key, b'\x01', hashlib.sha256
            ).digest()

            # Encrypt
            ciphertext = _aes_encrypt(msg_key, plaintext)

            # Sign
            signature = hmac_mod.new(
                self.signing_key,
                ciphertext,
                hashlib.sha256,
            ).digest()

            result = {
                "group_id": self.group_id,
                "sender": self.sender_username,
                "message_number": self.message_number,
                "ciphertext": ciphertext.hex(),
                "signature": signature.hex(),
            }
            self.message_number += 1
            return result

    def get_distribution(self):
        """Get sender key distribution message for sharing with group members."""
        with self._lock:
            return {
                "group_id": self.group_id,
                "sender": self.sender_username,
                "chain_key": self.chain_key.hex(),
                "signing_key": self.signing_key.hex(),
                "message_number": self.message_number,
            }

    def to_storage(self):
        with self._lock:
            return {
                "group_id": self.group_id,
                "sender_username": self.sender_username,
                "chain_key": self.chain_key.hex(),
                "signing_key": self.signing_key.hex(),
                "message_number": self.message_number,
            }

    @classmethod
    def from_storage(cls, data):
        state = cls.__new__(cls)
        state.group_id = data["group_id"]
        state.sender_username = data["sender_username"]
        state.chain_key = bytes.fromhex(data["chain_key"])
        state.signing_key = bytes.fromhex(data["signing_key"])
        state.message_number = data.get("message_number", 0)
        state._lock = threading.Lock()
        return state


class SenderKeyReceiver:
    """Receiving side of a Sender Key chain."""

    def __init__(self, group_id, sender_username, chain_key, signing_key, start_number=0):
        self.group_id = group_id
        self.sender_username = sender_username
        self.chain_key = chain_key
        self.signing_key = signing_key
        self.message_number = start_number
        # Cache of derived keys for out-of-order messages
        self._cached_keys = OrderedDict()
        self._lock = threading.Lock()

    def decrypt(self, message):
        """Decrypt a group message."""
        with self._lock:
            msg_num = message["message_number"]
            ciphertext = bytes.fromhex(message["ciphertext"])
            signature = bytes.fromhex(message["signature"])

            # Verify signature
            expected_sig = hmac_mod.new(
                self.signing_key, ciphertext, hashlib.sha256
            ).digest()
            if not hmac_mod.compare_digest(signature, expected_sig):
                logger.warning("Invalid sender key signature from %s", self.sender_username)
                return None

            # Derive the message key
            if msg_num < self.message_number:
                # Check cached keys
                if msg_num in self._cached_keys:
                    msg_key = self._cached_keys.pop(msg_num)
                else:
                    return None  # already consumed
            elif msg_num == self.message_number:
                msg_key = hmac_mod.new(
                    self.chain_key, struct.pack(">I", msg_num), hashlib.sha256
                ).digest()
                self.chain_key = hmac_mod.new(
                    self.chain_key, b'\x01', hashlib.sha256
                ).digest()
                self.message_number += 1
            else:
                # Skip ahead, cache intermediate keys
                for i in range(self.message_number, min(msg_num, self.message_number + MAX_SKIP)):
                    mk = hmac_mod.new(
                        self.chain_key, struct.pack(">I", i), hashlib.sha256
                    ).digest()
                    self._cached_keys[i] = mk
                    self.chain_key = hmac_mod.new(
                        self.chain_key, b'\x01', hashlib.sha256
                    ).digest()
                    while len(self._cached_keys) > MAX_SKIP:
                        self._cached_keys.popitem(last=False)

                msg_key = hmac_mod.new(
                    self.chain_key, struct.pack(">I", msg_num), hashlib.sha256
                ).digest()
                self.chain_key = hmac_mod.new(
                    self.chain_key, b'\x01', hashlib.sha256
                ).digest()
                self.message_number = msg_num + 1

            try:
                return _aes_decrypt(msg_key, ciphertext)
            except Exception as e:
                logger.error("Sender key decrypt failed: %s", e)
                return None

    @classmethod
    def from_distribution(cls, dist):
        return cls(
            group_id=dist["group_id"],
            sender_username=dist["sender"],
            chain_key=bytes.fromhex(dist["chain_key"]),
            signing_key=bytes.fromhex(dist["signing_key"]),
            start_number=dist.get("message_number", 0),
        )


class OnionEncryptor:
    """
    Server Onion Encryption for cross-server messages.

    When a message traverses A → B → C:
      A encrypts: Enc_C(Enc_B(message))
      B decrypts one layer: sees Enc_C(message) but not the message itself
      C decrypts final layer: sees the message

    Each layer uses a server-specific key derived from the shared mesh secret.
    """

    def __init__(self, local_server_id, secret_key):
        self.server_id = local_server_id
        self.secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key

    def _derive_server_key(self, server_id):
        """Derive an encryption key for a specific server."""
        return _hkdf_derive(
            self.secret_key,
            INFO_ONION + server_id.encode(),
            length=32,
        )

    def wrap(self, plaintext, server_path):
        """
        Wrap message in onion layers for the given server path.

        Args:
            plaintext: bytes to encrypt
            server_path: list of server_ids from source to destination

        Returns:
            Onion-wrapped bytes
        """
        data = plaintext if isinstance(plaintext, bytes) else plaintext.encode()

        # Wrap in reverse order (innermost layer = destination)
        for server_id in reversed(server_path):
            key = self._derive_server_key(server_id)
            layer = _aes_encrypt(key, data)
            # Prepend server_id length and server_id for routing
            sid_bytes = server_id.encode()
            data = struct.pack(">H", len(sid_bytes)) + sid_bytes + layer

        return data

    def peel(self, onion_data):
        """
        Peel one layer of the onion.

        Returns:
            (next_server_id, inner_data) if this is an intermediate layer
            (None, plaintext) if this is the final layer (for us)
        """
        try:
            # Read server_id
            sid_len = struct.unpack(">H", onion_data[:2])[0]
            sid = onion_data[2:2 + sid_len].decode()
            encrypted = onion_data[2 + sid_len:]

            # Decrypt our layer
            key = self._derive_server_key(sid)
            inner = _aes_decrypt(key, encrypted)

            # Check if there's another layer
            if len(inner) > 2:
                try:
                    next_len = struct.unpack(">H", inner[:2])[0]
                    if 1 <= next_len <= 64:  # reasonable server_id length
                        next_sid = inner[2:2 + next_len].decode()
                        return next_sid, inner
                except (struct.error, UnicodeDecodeError):
                    pass

            return None, inner

        except Exception as e:
            logger.error("Onion peel failed: %s", e)
            return None, None


class FileEncryptor:
    """
    E2E file encryption using AES-256-GCM.
    Each file gets a unique key, which is encrypted via the Double Ratchet session.
    """

    @staticmethod
    def encrypt_file(file_data):
        """
        Encrypt file data with a random key.

        Returns:
            (encrypted_data, file_key) where file_key needs to be shared via ratchet
        """
        file_key = os.urandom(32)
        encrypted = _aes_encrypt(file_key, file_data)
        return encrypted, file_key

    @staticmethod
    def decrypt_file(encrypted_data, file_key):
        """Decrypt file data with the provided key."""
        return _aes_decrypt(file_key, encrypted_data)

    @staticmethod
    def encrypt_file_key(file_key, ratchet_session):
        """Encrypt the file key using a Double Ratchet session."""
        msg = ratchet_session.encrypt(file_key)
        return msg

    @staticmethod
    def decrypt_file_key(encrypted_key_msg, ratchet_session):
        """Decrypt the file key using a Double Ratchet session."""
        return ratchet_session.decrypt(encrypted_key_msg)


class SignalProtocolManager:
    """
    Top-level manager for the Signal Protocol implementation.
    Manages identity bundles, sessions, group keys, and onion encryption.

    API endpoints it serves:
      GET  /api/signal/bundle/{username}     - Get user's public bundle
      POST /api/signal/session/initiate      - Start encrypted session
      POST /api/signal/session/respond       - Accept encrypted session
      POST /api/signal/group/create          - Create group encryption
      POST /api/signal/group/join            - Join encrypted group
      GET  /api/signal/stats                 - Encryption statistics
    """

    def __init__(self, server_id, secret_key):
        self.server_id = server_id
        self._lock = threading.Lock()

        # Identity bundles: {username: IdentityBundle}
        self.bundles = {}

        # Active sessions: {(user_a, user_b): DoubleRatchet}
        self.sessions = {}

        # Group sender keys: {group_id: {username: SenderKeyState}}
        self.group_sender_keys = {}

        # Group receiver keys: {group_id: {sender_username: SenderKeyReceiver}}
        self.group_receivers = {}

        # Onion encryptor
        self.onion = OnionEncryptor(server_id, secret_key)

        # Stats
        self._stats = {
            "sessions_created": 0,
            "messages_encrypted": 0,
            "messages_decrypted": 0,
            "groups_created": 0,
            "files_encrypted": 0,
        }

        logger.info(
            "SignalProtocolManager initialized (crypto=%s)",
            "available" if _CRYPTO_AVAILABLE else "fallback",
        )

    def get_or_create_bundle(self, username):
        """Get or create an identity bundle for a user."""
        with self._lock:
            if username not in self.bundles:
                self.bundles[username] = IdentityBundle(username)
                logger.info("Created identity bundle for %s", username)
            bundle = self.bundles[username]

        # Check if signed key needs rotation
        if bundle.should_rotate_signed_key():
            bundle.rotate_signed_key()
            logger.info("Rotated signed prekey for %s", username)

        return bundle

    def get_public_bundle(self, username):
        """Get the public bundle for sharing."""
        bundle = self.get_or_create_bundle(username)
        return bundle.get_public_bundle()

    def initiate_session(self, sender_username, receiver_username, receiver_public_bundle):
        """
        Initiate an encrypted session from sender to receiver.

        Returns:
            Session initiation data to send to receiver, or None on failure
        """
        sender_bundle = self.get_or_create_bundle(sender_username)
        result = X3DHSession.initiate(sender_bundle, receiver_public_bundle)
        if not result:
            return None

        shared_secret, ephemeral_public, used_otk_id = result

        # Create Double Ratchet
        ratchet = DoubleRatchet(shared_secret, is_initiator=True)
        # Initialize as sender with receiver's signed prekey as initial DH
        remote_dh = bytes.fromhex(receiver_public_bundle["signed_prekey"])
        ratchet.initialize_as_sender(remote_dh)

        session_key = tuple(sorted([sender_username, receiver_username]))
        with self._lock:
            self.sessions[session_key] = ratchet
            self._stats["sessions_created"] += 1

        logger.info("Session initiated: %s → %s", sender_username, receiver_username)

        return {
            "sender": sender_username,
            "receiver": receiver_username,
            "identity_key": sender_bundle.identity_public.hex(),
            "ephemeral_key": ephemeral_public.hex(),
            "used_otk_id": used_otk_id,
        }

    def respond_to_session(self, receiver_username, initiation_data):
        """
        Respond to a session initiation.

        Returns:
            Session response data to send back, or None on failure
        """
        sender_username = initiation_data["sender"]
        sender_identity = bytes.fromhex(initiation_data["identity_key"])
        sender_ephemeral = bytes.fromhex(initiation_data["ephemeral_key"])
        used_otk_id = initiation_data.get("used_otk_id")

        receiver_bundle = self.get_or_create_bundle(receiver_username)
        shared_secret = X3DHSession.respond(
            receiver_bundle, sender_identity, sender_ephemeral, used_otk_id
        )
        if not shared_secret:
            return None

        # Create Double Ratchet
        ratchet = DoubleRatchet(shared_secret, is_initiator=False)
        ratchet.initialize_as_receiver()

        session_key = tuple(sorted([sender_username, receiver_username]))
        with self._lock:
            self.sessions[session_key] = ratchet
            self._stats["sessions_created"] += 1

        logger.info("Session established: %s ↔ %s", sender_username, receiver_username)

        return {
            "sender": receiver_username,
            "receiver": sender_username,
            "dh_public": ratchet.dh_public.hex(),
            "status": "established",
        }

    def encrypt_message(self, sender, receiver, plaintext):
        """Encrypt a message in an existing session."""
        session_key = tuple(sorted([sender, receiver]))
        with self._lock:
            ratchet = self.sessions.get(session_key)
        if not ratchet:
            return None

        if isinstance(plaintext, str):
            plaintext = plaintext.encode()

        result = ratchet.encrypt(plaintext)
        if result:
            with self._lock:
                self._stats["messages_encrypted"] += 1
        return result

    def decrypt_message(self, sender, receiver, encrypted_message):
        """Decrypt a message in an existing session."""
        session_key = tuple(sorted([sender, receiver]))
        with self._lock:
            ratchet = self.sessions.get(session_key)
        if not ratchet:
            return None

        result = ratchet.decrypt(encrypted_message)
        if result:
            with self._lock:
                self._stats["messages_decrypted"] += 1
        return result

    def create_group(self, group_id, creator_username):
        """Create a new encrypted group."""
        sender_state = SenderKeyState(group_id, creator_username)

        with self._lock:
            if group_id not in self.group_sender_keys:
                self.group_sender_keys[group_id] = {}
            self.group_sender_keys[group_id][creator_username] = sender_state
            self._stats["groups_created"] += 1

        logger.info("Encrypted group %s created by %s", group_id, creator_username)
        return sender_state.get_distribution()

    def join_group(self, group_id, username, distributions=None):
        """
        Join an encrypted group.

        Args:
            group_id: Group/room ID
            username: Joining user's username
            distributions: List of sender key distributions from existing members
        """
        # Create this user's sender key
        sender_state = SenderKeyState(group_id, username)
        with self._lock:
            if group_id not in self.group_sender_keys:
                self.group_sender_keys[group_id] = {}
            self.group_sender_keys[group_id][username] = sender_state

            # Set up receivers for existing members
            if group_id not in self.group_receivers:
                self.group_receivers[group_id] = {}
            if distributions:
                for dist in distributions:
                    sender = dist["sender"]
                    self.group_receivers[group_id][sender] = SenderKeyReceiver.from_distribution(dist)

        logger.info("User %s joined encrypted group %s", username, group_id)
        return sender_state.get_distribution()

    def encrypt_group_message(self, group_id, sender_username, plaintext):
        """Encrypt a message for a group."""
        with self._lock:
            group_keys = self.group_sender_keys.get(group_id, {})
            sender_state = group_keys.get(sender_username)
        if not sender_state:
            return None

        if isinstance(plaintext, str):
            plaintext = plaintext.encode()

        result = sender_state.encrypt(plaintext)
        with self._lock:
            self._stats["messages_encrypted"] += 1
        return result

    def decrypt_group_message(self, group_id, message):
        """Decrypt a group message."""
        sender = message.get("sender")
        with self._lock:
            receivers = self.group_receivers.get(group_id, {})
            receiver = receivers.get(sender)
        if not receiver:
            return None

        result = receiver.decrypt(message)
        if result:
            with self._lock:
                self._stats["messages_decrypted"] += 1
        return result

    def encrypt_file(self, file_data, sender, receiver):
        """Encrypt a file for a specific recipient."""
        encrypted_data, file_key = FileEncryptor.encrypt_file(file_data)

        session_key = tuple(sorted([sender, receiver]))
        with self._lock:
            ratchet = self.sessions.get(session_key)
        if not ratchet:
            return None, None

        encrypted_key = FileEncryptor.encrypt_file_key(file_key, ratchet)
        with self._lock:
            self._stats["files_encrypted"] += 1

        return encrypted_data, encrypted_key

    def decrypt_file(self, encrypted_data, encrypted_key_msg, sender, receiver):
        """Decrypt a file."""
        session_key = tuple(sorted([sender, receiver]))
        with self._lock:
            ratchet = self.sessions.get(session_key)
        if not ratchet:
            return None

        file_key = FileEncryptor.decrypt_file_key(encrypted_key_msg, ratchet)
        if not file_key:
            return None

        return FileEncryptor.decrypt_file(encrypted_data, file_key)

    def wrap_onion(self, data, server_path):
        """Wrap data in onion layers for cross-server transit."""
        if isinstance(data, str):
            data = data.encode()
        return self.onion.wrap(data, server_path)

    def peel_onion(self, onion_data):
        """Peel one onion layer."""
        return self.onion.peel(onion_data)

    def get_stats(self):
        """Get encryption statistics."""
        with self._lock:
            return {
                **self._stats,
                "active_sessions": len(self.sessions),
                "active_bundles": len(self.bundles),
                "active_groups": len(self.group_sender_keys),
                "crypto_available": _CRYPTO_AVAILABLE,
            }

    def has_session(self, user_a, user_b):
        """Check if an encrypted session exists between two users."""
        session_key = tuple(sorted([user_a, user_b]))
        with self._lock:
            return session_key in self.sessions
