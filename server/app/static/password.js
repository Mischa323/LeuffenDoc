/* Making a password, to the rules set under Instellingen.

   Used where a password is made and on the settings page itself, so the
   example shown there is exactly what the button will produce. */
(function () {
  "use strict";

  const LOWER = "abcdefghijklmnopqrstuvwxyz";
  const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const DIGITS = "0123456789";
  // Characters that are read wrong off a screen and then fail when typed into
  // a console that has no clipboard.
  const LOOKALIKES = new Set("lIO01");

  // A uniform number below n. Plain `random % n` favours the low numbers
  // slightly; drawing again past the last whole multiple does not.
  function below(n) {
    const limit = Math.floor(0x100000000 / n) * n;
    const one = new Uint32Array(1);
    do { crypto.getRandomValues(one); } while (one[0] >= limit);
    return one[0] % n;
  }

  const pick = (alphabet) => alphabet[below(alphabet.length)];

  // Fisher-Yates, so the guaranteed characters are not always at the front.
  function shuffle(list) {
    for (let i = list.length - 1; i > 0; i--) {
      const j = below(i + 1);
      [list[i], list[j]] = [list[j], list[i]];
    }
    return list;
  }

  window.makePassword = function (cfg) {
    cfg = cfg || {};
    const length = Math.max(4, Number(cfg.PW_LENGTH) || 20);
    const wanted = [];
    if (cfg.PW_LOWER !== false) wanted.push(LOWER);
    if (cfg.PW_UPPER !== false) wanted.push(UPPER);
    if (cfg.PW_DIGITS !== false) wanted.push(DIGITS);
    if (cfg.PW_SYMBOLS !== false) wanted.push(cfg.PW_SYMBOL_SET || "!@#%^&*-_=+");
    const sets = wanted
      .map((set) => (cfg.PW_NO_LOOKALIKES !== false
        ? [...set].filter((c) => !LOOKALIKES.has(c)).join("") : set))
      .filter((set) => set.length);
    if (!sets.length) sets.push(LOWER + UPPER + DIGITS);
    const all = [...new Set(sets.join(""))].join("");

    const chars = [];
    // One from every kind that is switched on, so a password meets a policy
    // that demands "at least one digit" every time rather than most times.
    if (cfg.PW_EACH_CLASS !== false) for (const set of sets) chars.push(pick(set));
    while (chars.length < length) chars.push(pick(all));
    return shuffle(chars).join("");
  };
})();
