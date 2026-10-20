"""Legacy Adyen CSE field format used by the published TGTG card flow.

Adapted from py-adyen-encrypt (MIT); see THIRD_PARTY_NOTICES.md.
Cryptographic operations use the existing cryptography dependency.
"""

import base64
from datetime import datetime, timezone
import json
import os

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESCCM


def parse_public_key(encoded):
    exponent, modulus = encoded.split("|")
    key = rsa.RSAPublicNumbers(int(exponent, 16), int(modulus, 16)).public_key()
    if key.key_size < 2048:
        raise ValueError("Unexpected encryption key size")
    return key


def encrypt_card(card, cvv, public_key):
    key = parse_public_key(public_key)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    result = {"type": "scheme"}
    fields = (
        ("number", card.number, "encryptedCardNumber"),
        ("expiryMonth", card.month, "encryptedExpiryMonth"),
        ("expiryYear", card.year, "encryptedExpiryYear"),
        ("cvc", cvv, "encryptedSecurityCode"),
    )
    for field, value, output in fields:
        plaintext = json.dumps({field: value, "generationtime": timestamp}).encode()
        aes_key, nonce = AESCCM.generate_key(bit_length=256), os.urandom(12)
        ciphertext = nonce + AESCCM(aes_key, tag_length=8).encrypt(nonce, plaintext, None)
        wrapped = key.encrypt(aes_key, padding.PKCS1v15())
        result[output] = "adyenjs_0_1_1${}${}".format(
            base64.b64encode(wrapped).decode(), base64.b64encode(ciphertext).decode()
        )
    return result
