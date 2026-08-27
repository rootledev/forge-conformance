"""FC-080 — icons (v1.3).

icon is optional: a builtin name rootle maps to its Nerd Font glyph
(github, gitlab, bitbucket, folder — rendered when the user enables
[ui] nerd_font) or a single literal glyph the terminal can render in
any mode. Rootle never guesses icons from names; shape validation
rejects multi-char non-builtin strings.
"""

from cases.registry import BUILTIN_ICONS, C, icon_conforms
from forge import fc_assert


def test_FC080_icon_shape_absent_builtin_or_single_glyph(adapter):
    c = C("FC-080")
    icon = adapter.init_reply.get("icon")
    fc_assert(icon_conforms(icon), *c,
              "icon must be absent, a builtin name "
              f"({'|'.join(BUILTIN_ICONS)}), or a single scalar glyph; "
              f"multi-char non-builtin strings are rejected by shape "
              f"validation: got {icon!r}")
    # Pin the rule itself, exactly as rootle validates it.
    for ok in (None, "github", "gitlab", "bitbucket", "folder", "◆", "Ω"):
        fc_assert(icon_conforms(ok), *c, f"shape rule must accept {ok!r}")
    for bad in ("folders", "GitHub", "nerd font", "", "git lab", 7, ["folder"]):
        fc_assert(not icon_conforms(bad), *c,
                  f"shape rule must reject multi-char non-builtin / non-string "
                  f"values: {bad!r}")
