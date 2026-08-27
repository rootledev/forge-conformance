"""FC-001..FC-005 — handshake (v1).

The first request after spawn is ``initialize`` with ``protocol: 1``
plus the advisory cache budget (§Handshake). The reply's shape is
load-bearing: a wrong protocol aborts stdio setup, ``name``/``icon``
render in the modeline, and capabilities gate UI surfaces.
"""

from cases.registry import C, icon_conforms
from forge import fc_assert


def test_FC001_initialize_echoes_protocol_1(adapter):
    c = C("FC-001")
    reply = adapter.init_reply
    fc_assert(isinstance(reply, dict), *c, f"initialize result is not an object: {reply!r}")
    fc_assert(reply.get("protocol") == 1, *c,
              "protocol must echo exactly the int 1 (anything else aborts "
              "stdio setup and rootle falls back to the GitHub provider "
              f"with a warning); got {reply.get('protocol')!r}")


def test_FC002_name_present_or_absent(adapter):
    c = C("FC-002")
    name = adapter.init_reply.get("name")
    fc_assert(name is None or (isinstance(name, str) and name.strip()), *c,
              "name is optional but when present must be a non-empty string "
              f"(shown as stdio:<name>): got {name!r}")


def test_FC003_capabilities_shape(adapter):
    c = C("FC-003")
    caps = adapter.init_reply.get("capabilities")
    fc_assert(caps is None or isinstance(caps, dict), *c,
              "capabilities is optional and defaults to everything enabled; "
              f"when present it must be an object: {caps!r}")
    if isinstance(caps, dict):
        for key, val in caps.items():
            fc_assert(isinstance(val, bool), *c,
                      f"capabilities.{key} must be a boolean (the UI degrades "
                      f"on false): got {val!r}")


def test_FC004_icon_is_builtin_name_or_single_glyph(adapter):
    c = C("FC-004")
    icon = adapter.init_reply.get("icon")
    fc_assert(icon_conforms(icon), *c,
              "icon is optional: a builtin name (github|gitlab|bitbucket|"
              "folder) rootle maps to its Nerd Font glyph when nerd_font is "
              "on, or a single literal glyph the terminal can render in any "
              f"mode; got {icon!r}")


def test_FC005_cache_budget_params_tolerated_when_absent(adapter):
    """rootle passes cache_bytes/cache_dir at every initialize (v1.2), but
    a provider must also handshake when they are absent — the budget is
    advisory and rootle never demands the reply use it."""
    c = C("FC-005")
    reply = adapter.request("initialize", {"protocol": 1})
    fc_assert(reply.get("protocol") == 1, *c,
              "a bare initialize (no cache_bytes/cache_dir) must still "
              f"handshake — the cache budget is advisory; got {reply!r}")
