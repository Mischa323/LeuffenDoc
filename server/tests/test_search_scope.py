"""Searching one customer: only what is there, and only where you may look."""
from app import database


def test_searching_inside_one_customer(admin, member, org, make):
    make(admin, "computer", "ZOEK-PC-01", {"role": "Desktop"})
    other = database.upsert_org("Zoek Elders BV")
    database.create_item(other, "computer", "ZOEK-PC-99", {}, by=None)

    everywhere = {r["name"] for r in admin.get("/api/search?q=zoek-pc").json()["results"]}
    assert {"ZOEK-PC-01", "ZOEK-PC-99"} <= everywhere
    here = admin.get(f"/api/search?q=zoek-pc&org={org['id']}").json()["results"]
    assert {r["name"] for r in here} == {"ZOEK-PC-01"}

    # A customer someone may not see is not there to search.
    assert member.get(f"/api/search?q=zoek-pc&org={other}").status_code == 404
    assert {r["name"] for r in member.get(f"/api/search?q=zoek-pc&org={org['id']}").json()["results"]} \
        == {"ZOEK-PC-01"}
