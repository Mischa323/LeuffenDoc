"""The sidebar: laid out for everyone by an administrator, and by each person
for themselves on top of that."""


LAYOUT = {"groups": [{"id": "netwerk", "label": "Netwerk", "sections": ["netwerken", "vpn", "configuraties"]},
                     {"id": "g-mijn", "label": "Mijn spul", "sections": ["wachtwoorden"]}],
          "hidden": ["patchkasten"]}


def test_an_administrator_sets_the_default(admin, viewer):
    assert admin.get("/api/sidebar").json() == {"default": None, "mine": None}
    assert viewer.put("/api/sidebar/default", json=LAYOUT).status_code == 403
    saved = admin.put("/api/sidebar/default", json=LAYOUT)
    assert saved.status_code == 200 and saved.json() == LAYOUT
    # Everyone sees it as the default.
    assert viewer.get("/api/sidebar").json()["default"] == LAYOUT
    assert admin.delete("/api/sidebar/default").status_code == 200
    assert viewer.get("/api/sidebar").json()["default"] is None


def test_everyone_lays_out_their_own(admin, viewer):
    mine = {"groups": [{"id": "g-1", "label": "", "sections": ["documenten", "documenten", "contacten"]}],
            "hidden": ["documenten", "vpn"]}
    saved = viewer.put("/api/sidebar/mine", json=mine).json()
    # A section once, and not both shown and hidden.
    assert saved == {"groups": [{"id": "g-1", "label": "", "sections": ["documenten", "contacten"]}], "hidden": ["vpn"]}
    assert viewer.get("/api/sidebar").json()["mine"] == saved
    assert admin.get("/api/sidebar").json()["mine"] is None          # only theirs
    assert viewer.delete("/api/sidebar/mine").status_code == 200
    assert viewer.get("/api/sidebar").json()["mine"] is None


def test_what_is_not_a_layout_is_refused(admin):
    bad = admin.put("/api/sidebar/mine", json={"groups": [{"id": "<script>", "sections": []}]})
    assert bad.status_code == 400
    odd = admin.put("/api/sidebar/mine", json={"groups": [{"id": "g1", "label": "x" * 99,
                                                           "sections": ["ok-section", "Nope!", "../etc"]}]}).json()
    assert odd["groups"][0]["label"] == "x" * 40 and odd["groups"][0]["sections"] == ["ok-section"]
    assert admin.put("/api/sidebar/mine", json={"groups": [{"id": f"g{i}"} for i in range(21)]}).status_code == 400
    admin.delete("/api/sidebar/mine")
