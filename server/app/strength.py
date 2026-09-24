"""How hard a password would be to guess -- roughly, and said as roughly.

Three grades rather than a number of bits: *zwak*, *matig*, *sterk*. What
decides the grade is length, variety, and whether it is a well-known word or
keyboard pattern with a few digits stuck on. That last one is what an attacker
tries first, and what turns ``Welkom2024!`` from eleven varied characters into
a password found in seconds.

Only the grade is stored, next to the encrypted password. The reason is not:
"only digits, seven long" in a database column is a hint to whoever steals it.
"""
from __future__ import annotations

import math

WEAK, FAIR, STRONG = 0, 1, 2

# What people type when asked for a password, in Dutch and English. Not a
# breach list -- the point is the pattern "word, then digits", not coverage.
COMMON = {
    "password", "passw", "pass", "wachtwoord", "wachtwrd", "welkom", "welcome", "hallo",
    "hello", "admin", "administrator", "beheer", "beheerder", "root", "user", "gebruiker",
    "guest", "gast", "test", "testen", "demo", "default", "changeme", "letmein", "login",
    "inloggen", "secret", "geheim", "master", "qwerty", "azerty", "qwertz", "asdf",
    "asdfgh", "zxcvbn", "iloveyou", "monkey", "dragon", "sunshine", "princess", "football",
    "voetbal", "baseball", "shadow", "superman", "batman", "trustno", "starwars", "whatever",
    "zomer", "winter", "lente", "herfst", "summer", "spring", "autumn", "fall",
    "januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
    "september", "oktober", "november", "december", "january", "february", "march",
    "may", "june", "july", "august", "october",
    "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "ajax", "feyenoord", "psv", "amsterdam", "rotterdam", "utrecht", "denhaag",
    "nederland", "holland", "netherlands", "kantoor", "office", "bedrijf", "company",
    "server", "router", "printer", "wifi", "internet", "netwerk", "network", "backup",
    "system", "systeem", "service", "support", "helpdesk", "company", "abc", "abcd",
    "abcdef", "abcdefg", "abcdefgh", "iloveu", "loveyou", "liefde", "schat", "poes",
    "hond", "kat", "doggy", "kitty", "michael", "jordan", "jennifer", "thomas", "daniel",
}

# Stretches along the alphabet, the digits or a keyboard row count as one
# character: nobody guesses "qwertyui" one key at a time.
_RUNS = ["abcdefghijklmnopqrstuvwxyz", "0123456789", "qwertyuiop", "asdfghjkl", "zxcvbnm",
         "azertyuiop", "qsdfghjklm", "wxcvbn", "1qaz2wsx3edc", "!@#$%^&*()"]
_RUNS += [r[::-1] for r in _RUNS]

# The usual swaps, so "P@ssw0rd" is recognised as what it is.
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
                       "@": "a", "$": "s", "!": "i", "|": "l"})


def _pool(password: str) -> int:
    pool = 0
    if any(c.islower() for c in password):
        pool += 26
    if any(c.isupper() for c in password):
        pool += 26
    if any(c.isdigit() for c in password):
        pool += 10
    if any(not c.isalnum() and c.isascii() for c in password):
        pool += 33
    if any(not c.isascii() for c in password):
        pool += 100
    return max(pool, 1)


def _effective_length(password: str) -> int:
    """Length, with a repeated character or a run along a row counted once."""
    low = password.lower()
    count, i, n = 0, 0, len(low)
    while i < n:
        j = i + 1
        while j < n and low[j] == low[i]:
            j += 1
        if j - i < 3:
            j = i + 1
            for k in range(i + 3, n + 1):
                if any(low[i:k] in run for run in _RUNS):
                    j = k
                else:
                    break
        count += 1 if j - i >= 3 else j - i
        i = j
    return count


def _core(password: str) -> str:
    """The word in the middle, without the digits and marks around it."""
    low = password.lower()
    start, end = 0, len(low)
    while start < end and not low[start].isalpha():
        start += 1
    while end > start and not low[end - 1].isalpha():
        end -= 1
    return low[start:end].translate(_LEET)


def rate(password: str) -> int:
    """WEAK, FAIR or STRONG."""
    if len(password) < 8:
        return WEAK
    core = _core(password)
    if core in COMMON or password.lower().translate(_LEET) in COMMON:
        return WEAK
    bits = _effective_length(password) * math.log2(_pool(password))
    if bits < 50:
        return WEAK
    if bits < 75:
        return FAIR
    return STRONG
