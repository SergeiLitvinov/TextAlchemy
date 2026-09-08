"""One-to-one matching of inspected objects without collapsing duplicates."""

from collections import defaultdict
from typing import Any, Callable

Object = dict[str, Any]


def match_objects(source: list[Object], target: list[Object]) -> tuple[list[Object], list[Object], list[Object]]:
    """Prefer provenance, then content, and use location only as a heuristic.

    Equal content cannot override conflicting explicit origins. Duplicate
    fingerprints remain separate occurrences; their pairing is marked ambiguous.
    """
    remaining_source, remaining_target = set(range(len(source))), set(range(len(target)))
    matches = []

    def origin(item: Object) -> str | None:
        return (item.get("provenance") or {}).get("identity") or None

    def compatible(before: Object, after: Object) -> bool:
        before_origin, after_origin = before.get("provenance") or {}, after.get("provenance") or {}
        if before_origin.get("source_format") and after_origin.get("source_format"):
            before_scope = (before_origin["source_format"], before_origin.get("source_path"))
            after_scope = (after_origin["source_format"], after_origin.get("source_path"))
            if before_scope != after_scope:
                return True  # Re-imported files have independent origin identifiers.
        return not (origin(before) and origin(after) and origin(before) != origin(after))

    def pair(left: int, right: int, basis: str, ambiguous: bool) -> None:
        matches.append({
            "source": source[left], "target": target[right], "match_basis": basis,
            "ambiguous": ambiguous, "source_index": left, "target_index": right,
        })
        remaining_source.remove(left)
        remaining_target.remove(right)

    def match_groups(key: Callable[[Object], Any], basis: str, *, unique: bool = False) -> None:
        left_groups, right_groups = defaultdict(list), defaultdict(list)
        for index in sorted(remaining_source):
            if (value := key(source[index])) is not None:
                left_groups[value].append(index)
        for index in sorted(remaining_target):
            if (value := key(target[index])) is not None:
                right_groups[value].append(index)
        for value, left in left_groups.items():
            right = right_groups.get(value, [])
            ambiguous = len(left) > 1 or len(right) > 1
            if unique and ambiguous:
                continue
            for index in left:
                candidates = [other for other in right if compatible(source[index], target[other])]
                if not candidates:
                    continue
                # Stable locations disambiguate equal fingerprints where possible.
                other = next((other for other in candidates if source[index].get("location") == target[other].get("location")),
                             candidates[0])
                pair(index, other, basis, ambiguous)
                right.remove(other)

    match_groups(lambda item: (item.get("type"), origin(item)) if origin(item) else None, "provenance", unique=True)
    match_groups(
        lambda item: (item.get("type"), origin(item), item["content_hash"])
        if origin(item) and item.get("content_hash") else None,
        "provenance-content",
    )
    match_groups(lambda item: (item.get("type"), item["content_hash"]) if item.get("content_hash") else None, "content")
    match_groups(lambda item: (item.get("type"), origin(item)) if origin(item) else None, "provenance", unique=True)
    match_groups(lambda item: (item.get("type"), item["location"]) if item.get("location") else None, "location")
    matches.sort(key=lambda item: item["source_index"])
    return matches, [source[index] for index in sorted(remaining_source)], [target[index] for index in sorted(remaining_target)]
