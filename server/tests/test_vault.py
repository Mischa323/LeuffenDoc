"""The vault's building blocks: sealing, fingerprints, and how strong a password is."""
import hashlib

import pytest

from app import strength, vault


def test_a_sealed_password_opens_to_what_it_was(server):
    record = vault.seal("Correct-Paard-Batterij-9")
    assert vault.unseal(record) == "Correct-Paard-Batterij-9"
    assert b"Correct-Paard" not in record["ciphertext"]


def test_an_altered_record_does_not_open(server):
    record = vault.seal("Onaangetast-1")
    record["ciphertext"] = bytes([record["ciphertext"][0] ^ 1]) + record["ciphertext"][1:]
    with pytest.raises(Exception):
        vault.unseal(record)


def test_two_seals_of_the_same_password_look_different(server):
    assert vault.seal("Twee-Keer-1")["ciphertext"] != vault.seal("Twee-Keer-1")["ciphertext"]


def test_the_fingerprint_finds_the_same_password_but_is_keyed(server):
    assert vault.fingerprint("Hetzelfde-1") == vault.fingerprint("Hetzelfde-1")
    assert vault.fingerprint("Hetzelfde-1") != vault.fingerprint("Hetzelfde-2")
    assert vault.fingerprint("Hetzelfde-1") != hashlib.sha256(b"Hetzelfde-1").hexdigest()


def test_a_sealed_record_survives_being_stored_as_text(server):
    record = vault.seal("Als-Tekst-1")
    assert vault.unseal(vault.unpack(vault.pack(record))) == "Als-Tekst-1"


@pytest.mark.parametrize("password,grade", [
    ("Welkom2024!", strength.WEAK),        # a well-known word with digits after it
    ("P@ssw0rd", strength.WEAK),           # the same, with the usual swaps
    ("12345678", strength.WEAK),           # a run along the digits
    ("aaaaaaaaaaaa", strength.WEAK),       # one character, repeated
    ("kort1!", strength.WEAK),             # too short to be anything
    ("Tr0ub4dor&3", strength.FAIR),
    ("Xk7#mQ2vL9pR4wZ8nB5t", strength.STRONG),
    ("correcthorsebatterystaple", strength.STRONG),
])
def test_strength(password, grade):
    assert strength.rate(password) == grade
