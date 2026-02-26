"""IFC parsing checker based on the assignment checker contract."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import ifcopenshell
try:
    from checker_barcelona_compliance import check_barcelona_space_compliance
except ImportError:
    from tools.checker_barcelona_compliance import check_barcelona_space_compliance


DEFAULT_ENTITY_TYPES = [
    "IfcProject",
    "IfcSite",
    "IfcBuilding",
    "IfcBuildingStorey",
    "IfcSpace",
    "IfcWall",
    "IfcSlab",
    "IfcDoor",
    "IfcWindow",
    "IfcColumn",
    "IfcBeam",
]

DEFAULT_IFC_PATH = (
    r"C:\Users\User\github-classroom\iaac-maai\intro-to-ifc-jineshnarendrajain\assets\duplex.ifc"
)


def _to_text(value: object) -> str:
    """Convert any value to a safe display string."""
    if value is None:
        return ""
    return str(value)


def _normalize_entity_types(entity_types: object) -> list[str]:
    """Normalize entity type input from kwargs."""
    if entity_types is None:
        return list(DEFAULT_ENTITY_TYPES)

    if isinstance(entity_types, str):
        parsed = [chunk.strip() for chunk in entity_types.split(",") if chunk.strip()]
        return parsed or list(DEFAULT_ENTITY_TYPES)

    if isinstance(entity_types, Iterable):
        parsed = [str(item).strip() for item in entity_types if str(item).strip()]
        return parsed or list(DEFAULT_ENTITY_TYPES)

    return list(DEFAULT_ENTITY_TYPES)


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
) -> dict:
    """Build a result row in the exact required schema."""
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


def check_ifc_parse(
    model: ifcopenshell.file,
    entity_types: object = None,
    sample_limit: int = 3,
    **kwargs,
) -> list[dict]:
    """Parse IFC model basics and emit normalized result rows."""
    del kwargs

    results: list[dict] = []
    entity_type_list = _normalize_entity_types(entity_types)
    sample_limit = max(1, int(sample_limit))

    schema_value = getattr(model, "schema", "unknown")
    if callable(schema_value):
        schema_value = schema_value()

    results.append(
        _result(
            element_id=None,
            element_type="Summary",
            element_name="Model Schema",
            element_name_long=None,
            check_status="log",
            actual_value=_to_text(schema_value) or "unknown",
            required_value="Readable IFC schema",
            comment="Parsed model schema successfully",
            log=None,
        )
    )

    total_count = 0

    for entity_type in entity_type_list:
        try:
            elements = model.by_type(entity_type)
        except Exception as exc:  # pragma: no cover - defensive path for bad IFC/schema
            results.append(
                _result(
                    element_id=None,
                    element_type="Summary",
                    element_name=f"{entity_type} Parse",
                    element_name_long=None,
                    check_status="blocked",
                    actual_value="0",
                    required_value="Parsable entity type",
                    comment=f"Could not parse {entity_type}",
                    log=_to_text(exc),
                )
            )
            continue

        count = len(elements)
        total_count += count

        results.append(
            _result(
                element_id=None,
                element_type="Summary",
                element_name=f"{entity_type} Count",
                element_name_long=None,
                check_status="pass" if count > 0 else "warning",
                actual_value=str(count),
                required_value=">= 1 recommended",
                comment=None if count > 0 else f"No {entity_type} elements found",
                log=None,
            )
        )

        for element in elements[:sample_limit]:
            global_id = getattr(element, "GlobalId", None)
            name = getattr(element, "Name", None)
            long_name = getattr(element, "LongName", None)
            express_id = getattr(element, "id", lambda: None)()

            results.append(
                _result(
                    element_id=_to_text(global_id) if global_id else None,
                    element_type=entity_type,
                    element_name=_to_text(name) or f"{entity_type} #{_to_text(express_id) or 'unknown'}",
                    element_name_long=_to_text(long_name) if long_name else None,
                    check_status="log",
                    actual_value=(
                        f"Parsed {entity_type} (express_id={_to_text(express_id) or 'unknown'})"
                    ),
                    required_value="Parsable IFC entity",
                    comment=None,
                    log=None,
                )
            )

    results.append(
        _result(
            element_id=None,
            element_type="Summary",
            element_name="Overall Parse",
            element_name_long=None,
            check_status="pass" if total_count > 0 else "warning",
            actual_value=f"{total_count} parsed entities across {len(entity_type_list)} types",
            required_value="> 0 parsed entities",
            comment=(
                "Model parsed successfully"
                if total_count > 0
                else "Model readable but no entities found for configured types"
            ),
            log=None,
        )
    )

    return results


def _build_parse_section(results: list[dict]) -> list[str]:
    """Build the IFC parse section lines."""

    def _clip(value: object, width: int) -> str:
        text = _to_text(value)
        if len(text) <= width:
            return text
        return text[: width - 3] + "..."

    summary_rows = [row for row in results if row.get("element_type") == "Summary"]
    detail_rows = [row for row in results if row.get("element_type") != "Summary"]

    status_counts: dict[str, int] = {}
    for row in results:
        status = _to_text(row.get("check_status")).lower() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    entity_count_rows: list[tuple[str, str, str]] = []
    for row in summary_rows:
        name = _to_text(row.get("element_name"))
        if not name.endswith(" Count"):
            continue
        entity_type = name[: -len(" Count")]
        entity_count_rows.append(
            (
                entity_type,
                _to_text(row.get("actual_value")),
                _to_text(row.get("check_status")).upper(),
            )
        )

    lines = [
        "A) IFC PARSE SUMMARY",
        "-" * 100,
        f"Total parse rows: {len(results)} (summary={len(summary_rows)}, details={len(detail_rows)})",
        "",
        "1) STATUS DISTRIBUTION",
        "-" * 100,
        f"{'Status':<12} {'Count':>8}",
        "-" * 100,
    ]

    for status in ["pass", "warning", "fail", "blocked", "log", "unknown"]:
        count = status_counts.get(status)
        if count is not None:
            lines.append(f"{status.upper():<12} {count:>8}")

    lines.extend(
        [
            "",
            "2) ENTITY COUNTS",
            "-" * 100,
            f"{'Entity Type':<30} {'Count':>8} {'Status':>12}",
            "-" * 100,
        ]
    )

    if entity_count_rows:
        for entity_type, count, status in entity_count_rows:
            lines.append(f"{_clip(entity_type, 30):<30} {count:>8} {status:>12}")
    else:
        lines.append("No entity count rows were generated.")

    lines.extend(
        [
            "",
            "3) SAMPLED ELEMENTS",
            "-" * 100,
            f"{'#':>3} {'Type':<18} {'Name':<34} {'GlobalId':<24} {'Note':<17}",
            "-" * 100,
        ]
    )

    if detail_rows:
        for idx, row in enumerate(detail_rows, start=1):
            lines.append(
                f"{idx:>3} "
                f"{_clip(row.get('element_type'), 18):<18} "
                f"{_clip(row.get('element_name'), 34):<34} "
                f"{_clip(row.get('element_id') or '-', 24):<24} "
                f"{_clip(row.get('check_status'), 17):<17}"
            )
    else:
        lines.append("No element-level sample rows found.")

    noteworthy = [
        row
        for row in results
        if _to_text(row.get("check_status")).lower() in {"warning", "fail", "blocked"}
    ]
    lines.extend(["", "4) PARSE WARNINGS / FAILURES / BLOCKED", "-" * 100])
    if noteworthy:
        for row in noteworthy:
            lines.append(
                f"- [{_to_text(row.get('check_status')).upper()}] "
                f"{_to_text(row.get('element_type'))} | {_to_text(row.get('element_name'))}"
            )
            if row.get("comment"):
                lines.append(f"  comment: {_to_text(row.get('comment'))}")
            if row.get("log"):
                lines.append(f"  log    : {_to_text(row.get('log'))}")
    else:
        lines.append("No warnings, failures, or blocked items.")

    lines.append("")
    return lines


def _build_compliance_section(results: list[dict]) -> list[str]:
    """Build the Barcelona compliance section lines."""

    def _clip(value: object, width: int) -> str:
        text = _to_text(value)
        if len(text) <= width:
            return text
        return text[: width - 3] + "..."

    summary_rows = [
        row for row in results if row.get("element_type") == "Summary"
    ]
    space_rows = [
        row for row in results if row.get("element_type") == "IfcSpace"
    ]

    status_counts: dict[str, int] = {}
    for row in space_rows:
        status = _to_text(row.get("check_status")).lower() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    lines = [
        "B) BARCELONA SPACE COMPLIANCE",
        "-" * 100,
        f"Total space checks: {len(space_rows)}",
        "",
        "1) COMPLIANCE STATUS COUNTS",
        "-" * 100,
        f"{'Status':<12} {'Count':>8}",
        "-" * 100,
    ]
    for status in ["pass", "fail", "warning", "blocked", "log", "unknown"]:
        count = status_counts.get(status)
        if count is not None:
            lines.append(f"{status.upper():<12} {count:>8}")

    lines.extend(
        [
            "",
            "2) SPACE-BY-SPACE RESULTS",
            "-" * 100,
            f"{'#':>3} {'Space':<26} {'Status':<8} {'Measured':<34} {'Required':<26}",
            "-" * 100,
        ]
    )

    if space_rows:
        for idx, row in enumerate(space_rows, start=1):
            lines.append(
                f"{idx:>3} "
                f"{_clip(row.get('element_name'), 26):<26} "
                f"{_clip(_to_text(row.get('check_status')).upper(), 8):<8} "
                f"{_clip(row.get('actual_value'), 34):<34} "
                f"{_clip(row.get('required_value'), 26):<26}"
            )
    else:
        lines.append("No IfcSpace rows found.")

    failed_or_warn = [
        row
        for row in space_rows
        if _to_text(row.get("check_status")).lower() in {"fail", "warning", "blocked"}
    ]
    lines.extend(["", "3) NON-COMPLIANT DETAILS", "-" * 100])
    if failed_or_warn:
        for row in failed_or_warn:
            lines.append(
                f"- [{_to_text(row.get('check_status')).upper()}] {_to_text(row.get('element_name'))}"
            )
            if row.get("comment"):
                lines.append(f"  reasons: {_to_text(row.get('comment'))}")
    else:
        lines.append("All checked spaces are compliant.")

    lines.extend(["", "4) COMPLIANCE SUMMARY ROWS", "-" * 100])
    if summary_rows:
        for row in summary_rows:
            lines.append(f"- {_to_text(row.get('element_name'))}: {_to_text(row.get('actual_value'))}")
            if row.get("comment"):
                lines.append(f"  comment: {_to_text(row.get('comment'))}")
    else:
        lines.append("No summary rows produced.")

    lines.append("")
    return lines


def _build_complete_report(
    ifc_path: str,
    parse_results: list[dict],
    compliance_results: list[dict],
) -> str:
    """Build full report content with parse and compliance sections."""
    divider = "=" * 100
    lines = [
        divider,
        "IFC COMPLETE REPORT (PARSE + BARCELONA COMPLIANCE)",
        divider,
        f"IFC file      : {ifc_path}",
        f"Generated at  : {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]

    lines.extend(_build_parse_section(parse_results))
    lines.extend(_build_compliance_section(compliance_results))
    lines.append(divider)
    return "\n".join(lines) + "\n"


def main() -> None:
    """Run parse and compliance checks and write one structured report."""
    ifc_file = Path(DEFAULT_IFC_PATH)
    if not ifc_file.exists():
        print(f"IFC file not found: {DEFAULT_IFC_PATH}")
        return

    model = ifcopenshell.open(str(ifc_file))
    parse_results = check_ifc_parse(model)
    compliance_results = check_barcelona_space_compliance(model)

    reports_dir = Path(__file__).resolve().parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"ifc_complete_report_{timestamp}.txt"
    report_path.write_text(
        _build_complete_report(DEFAULT_IFC_PATH, parse_results, compliance_results),
        encoding="utf-8",
    )

    print(f"Report generated: {report_path}")
    print(f"Parse rows written: {len(parse_results)}")
    print(f"Compliance rows written: {len(compliance_results)}")


if __name__ == "__main__":
    main()
