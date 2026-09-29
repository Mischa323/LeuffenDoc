"""Virtual machines on Hyper-V hosts become configurations, "Draait op" their host."""
from app import database, docpush, rmm


def test_hyperv_guests_are_documented(server, monkeypatch):
    org_id = database.upsert_org("Hyper-V BV", rmm_org_id="org-hv")
    host = {"id": "dev-hv01", "hostname": "HV-01", "org": {"id": "org-hv"},
            "hyperv": [{"name": "VM-APP", "state": "Running", "vcpu": 4, "mem_assigned": 8 * 1024 ** 3},
                       {"name": "WS-AGENT", "state": "Running", "vcpu": 2}]}
    agent = {"id": "dev-agent", "hostname": "WS-AGENT", "org": {"id": "org-hv"}}
    monkeypatch.setattr(rmm, "fetch_devices", lambda: [host, agent])
    rmm.sync_devices()
    items = {i["name"]: i for i in database.list_items(org_id)}
    vm, hv = items["VM-APP"], items["HV-01"]
    assert vm["fields"]["role"] == "Virtuele machine" and vm["fields"]["host"] == hv["id"]
    assert vm["rmm"]["cpu"] == "4 vCPU" and vm["rmm"]["vm_state"] == "Draait"
    # A guest with an agent of its own is that device, told where it runs.
    assert [n for n in items if n == "WS-AGENT"] == ["WS-AGENT"]
    assert items["WS-AGENT"]["fields"]["host"] == hv["id"]
    # VMs are no devices in the RMM, so nothing is sent there for them.
    assert not any(k.startswith(rmm.VM_PREFIX) for k in docpush.wanted())
    # One the host no longer reports keeps its page and says so.
    host["hyperv"] = [host["hyperv"][1]]
    rmm.sync_devices()
    assert database.get_item(vm["id"])["rmm_gone"] is True
