"""Barcelona/Catalan basic space compliance checker for IFC spaces."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

import ifcopenshell


SPACE_RULES = {
    "Living Room": {"min_height": 2.6, "min_area": 16.0},
    "Bedroom": {"min_height": 2.6, "min_area": 9.0},
    "Kitchen": {"min_height": 2.6, "min_area": 8.0},
    "Bathroom": {"min_height": 2.3, "min_area": 4.0},
    "Corridor": {"min_height": 2.3, "min_area": 1.5},
}

SPACE_KEYWORDS = {
    "Living Room": ["living", "lounge", "sala", "salon", "estar", "menjador"],
    "Bedroom": ["bedroom", "bed", "dorm", "habitacio", "habitacio", "dormitori"],
    "Kitchen": ["kitchen", "cuina", "cocina"],
    "Bathroom": ["bath", "bathroom", "toilet", "wc", "lavabo", "aseo", "bany"],
    "Corridor": ["corridor", "hall", "pasillo", "passage", "rebedor", "distrib"],
}

QTO_AREA_NAMES = {"netfloorarea", "grossfloorarea", "floorarea"}
QTO_HEIGHT_NAMES = {"height", "clearheight", "netheight"}


def _norm_text(value: object) -> str:
    """Normalize text for robust matching."""
    if value is None:
        return ""

    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def _to_float(value: object) -> float | None:
    """Best-effort conversion to float."""
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        pass

    wrapped = getattr(value, "wrappedValue", None)
    if wrapped is not None:
        try:
            return float(wrapped)
        except (TypeError, ValueError):
            return None

    return None


def _get_space_type(space: ifcopenshell.entity_instance) -> str | None:
    """Classify a space type from Name/LongName/ObjectType keywords."""
    haystack = " ".join(
        [
            _norm_text(getattr(space, "Name", None)),
            _norm_text(getattr(space, "LongName", None)),
            _norm_text(getattr(space, "ObjectType", None)),
        ]
    )

    for space_type, keywords in SPACE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in haystack:
                return space_type

    return None


def _iter_property_defs(space: ifcopenshell.entity_instance):
    """Yield property definitions linked to a space via IfcRelDefinesByProperties."""
    for rel in getattr(space, "IsDefinedBy", []) or []:
        if not rel or not rel.is_a("IfcRelDefinesByProperties"):
            continue

        prop_def = getattr(rel, "RelatingPropertyDefinition", None)
        if prop_def:
            yield prop_def


def _extract_area_m2(space: ifcopenshell.entity_instance) -> float | None:
    """Extract area using required precedence logic."""
    # 1) Quantity takeoff preferred names
    for prop_def in _iter_property_defs(space):
        if not prop_def.is_a("IfcElementQuantity"):
            continue

        for q in getattr(prop_def, "Quantities", []) or []:
            if not q or not q.is_a("IfcQuantityArea"):
                continue

            qname = _norm_text(getattr(q, "Name", None))
            if qname in QTO_AREA_NAMES:
                return _to_float(getattr(q, "AreaValue", None))

    # 2) Property set fallback: any property with "area" in name
    for prop_def in _iter_property_defs(space):
        if not prop_def.is_a("IfcPropertySet"):
            continue

        for prop in getattr(prop_def, "HasProperties", []) or []:
            pname = _norm_text(getattr(prop, "Name", None))
            if "area" not in pname:
                continue

            nominal = getattr(prop, "NominalValue", None)
            val = _to_float(nominal)
            if val is not None:
                return val

    return None


def _extract_height_m(space: ifcopenshell.entity_instance) -> float | None:
    """Extract height using required precedence logic."""
    # 1) Quantity takeoff preferred names
    for prop_def in _iter_property_defs(space):
        if not prop_def.is_a("IfcElementQuantity"):
            continue

        for q in getattr(prop_def, "Quantities", []) or []:
            if not q or not q.is_a("IfcQuantityLength"):
                continue

            qname = _norm_text(getattr(q, "Name", None))
            if qname in QTO_HEIGHT_NAMES:
                return _to_float(getattr(q, "LengthValue", None))

    # 2) Property set fallback: any property with "height" in name
    for prop_def in _iter_property_defs(space):
        if not prop_def.is_a("IfcPropertySet"):
            continue

        for prop in getattr(prop_def, "HasProperties", []) or []:
            pname = _norm_text(getattr(prop, "Name", None))
            if "height" not in pname:
                continue

            nominal = getattr(prop, "NominalValue", None)
            val = _to_float(nominal)
            if val is not None:
                return val

    return None


def _format_decimal(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "None"
    return f"{value:.{digits}f}"


def _result(
    *,
    element_id: str | None,
    element_type: str,
    element_name: str,
    element_name_long: str | None,
    check_status: str,
    actual_value: str,
    required_value: str,
    comment: str | None,
    log: str | None,
) -> dict[str, Any]:
    return {
        "element_id": element_id,
        "element_type": element_type,
        "element_name": element_name,
        "element_name_long": element_name_long,
        "check_status": check_status,
        "actual_value": actual_value,
        "required_value": required_value,
        "comment": comment,
        "log": log,
    }


def check_barcelona_space_compliance(model: ifcopenshell.file, **kwargs) -> list[dict[str, Any]]:
    """Check IfcSpace minimum area/height compliance using provided Catalan rules."""
    del kwargs

    spaces = model.by_type("IfcSpace")
    results: list[dict[str, Any]] = []

    passed = 0
    failed = 0
    warnings = 0

    for space in spaces:
        name = getattr(space, "Name", None) or f"IfcSpace #{space.id()}"
        long_name = getattr(space, "LongName", None)
        space_type = _get_space_type(space)

        area = _extract_area_m2(space)
        height = _extract_height_m(space)

        reasons: list[str] = []
        required_area: float | None = None
        required_height: float | None = None

        if not space_type:
            reasons.append("Could not infer space type")
        else:
            rule = SPACE_RULES.get(space_type)
            if not rule:
                reasons.append(f"Unrecognized space type: {space_type}")
            else:
                required_area = rule["min_area"]
                required_height = rule["min_height"]

        if area is None:
            reasons.append("Area not found.")
        elif required_area is not None and area < required_area:
            reasons.append(f"Area {area:.3f} m2 < required {required_area:.3f} m2.")

        if height is None:
            reasons.append("Height not found.")
        elif required_height is not None and height < required_height:
            reasons.append(f"Height {height:.3f} m < required {required_height:.3f} m.")

        is_pass = len(reasons) == 0
        status = "pass" if is_pass else "fail"

        if is_pass:
            passed += 1
            reasons = ["Meets minimum area and height requirements."]
        else:
            failed += 1

        structured_output = {
            "space": str(name),
            "space_type": space_type,
            "measured": {
                "area_m2": area,
                "height_m": height,
            },
            "required": {
                "min_area_m2": required_area,
                "min_height_m": required_height,
            },
            "status": "PASS" if is_pass else "FAIL",
            "reasons": reasons,
        }

        results.append(
            _result(
                element_id=getattr(space, "GlobalId", None),
                element_type="IfcSpace",
                element_name=str(name),
                element_name_long=str(long_name) if long_name else None,
                check_status=status,
                actual_value=(
                    f"space_type={space_type or 'unknown'}, "
                    f"area_m2={_format_decimal(area)}, "
                    f"height_m={_format_decimal(height)}"
                ),
                required_value=(
                    f"min_area_m2={_format_decimal(required_area)}, "
                    f"min_height_m={_format_decimal(required_height)}"
                ),
                comment="; ".join(reasons),
                log=json.dumps(structured_output, ensure_ascii=True),
            )
        )

    total_input = len(spaces)
    total_checked = total_input
    compliance_rate = (passed / total_checked * 100.0) if total_checked > 0 else 0.0

    summary = {
        "total_spaces_input": total_input,
        "total_spaces_checked": total_checked,
        "passed_count": passed,
        "failed_count": failed,
        "warnings_count": warnings,
        "compliance_rate_percent": round(compliance_rate, 2),
    }

    results.append(
        _result(
            element_id=None,
            element_type="Summary",
            element_name="Barcelona Space Compliance Summary",
            element_name_long=None,
            check_status="pass" if failed == 0 else "fail",
            actual_value=(
                f"checked={total_checked}, passed={passed}, failed={failed}, "
                f"warnings={warnings}, rate={compliance_rate:.2f}%"
            ),
            required_value="All checked spaces should meet minimum area and height by inferred space type",
            comment=(
                "No IfcSpace elements found" if total_checked == 0 else "Computed from provided Barcelona rules"
            ),
            log=json.dumps(summary, ensure_ascii=True),
        )
    )

    return results
