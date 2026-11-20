"""English system record names with compatibility for saved legacy names."""

LEGACY_RECORD_NAMES = {
    "Top left": "\u5de6\u4e0a",
    "Top right": "\u53f3\u4e0a",
    "Bottom right": "\u53f3\u4e0b",
    "Bottom left": "\u5de6\u4e0b",
    "Reset hover": "reset\u60ac\u7a7a\u9884\u5907"
}

def canonical_record_name(name):
    for canonical, legacy in LEGACY_RECORD_NAMES.items():
        if name == legacy:
            return canonical
    return name

def resolve_record_name(records, name):
    if name in records:
        return name
    canonical = canonical_record_name(name)
    if canonical in records:
        return canonical
    legacy = LEGACY_RECORD_NAMES.get(canonical)
    return legacy if legacy in records else name
