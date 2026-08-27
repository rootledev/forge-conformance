"""The registry is the contract: stable numbered cases, citable across
adapters, docs, and bug reports. This gate pins the plan-0015
enumeration plus the v1.5 revision group (plan-0016 M1) — the case
never renames, the set never silently shrinks."""


from cases.registry import CASES

PLAN_ENUMERATION = {
    "FC-001", "FC-002", "FC-003", "FC-004", "FC-005",
    "FC-010", "FC-011", "FC-012", "FC-013",
    "FC-020", "FC-021", "FC-022", "FC-023", "FC-024", "FC-025",
    "FC-030", "FC-031", "FC-032", "FC-033", "FC-034",
    "FC-040", "FC-041", "FC-042", "FC-043", "FC-044", "FC-045",
    "FC-050", "FC-051", "FC-052", "FC-053", "FC-054",
    "FC-060", "FC-061", "FC-062", "FC-063",
    "FC-070",
    "FC-080",
    # v1.5 revisions (plans/0016 M1)
    "FC-090", "FC-091", "FC-092", "FC-093", "FC-094",
    "FC-095", "FC-096", "FC-097", "FC-098", "FC-099",
}


def test_registry_matches_the_plan_enumeration():
    have = set(CASES)
    assert have == PLAN_ENUMERATION, (
        f"registry drifted from plans/0015: missing "
        f"{sorted(PLAN_ENUMERATION - have)}, extra {sorted(have - PLAN_ENUMERATION)}"
    )


def test_every_case_entry_is_complete():
    for cid, (module, title, spec) in CASES.items():
        assert module.startswith("test_"), (cid, module)
        assert title and spec, (cid, title, spec)
