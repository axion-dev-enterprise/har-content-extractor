"""
Exporter — Exports extracted data to Excel, CSV, or JSON formats.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


def _flatten_record(record: dict, parent_key: str = "", sep: str = ".") -> dict:
    """Flatten nested dicts into dot-separated keys for tabular export."""
    items: list[tuple[str, Any]] = []
    for k, v in record.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_record(v, new_key, sep).items())
        elif isinstance(v, list):
            # Join lists into comma-separated strings
            items.append((new_key, ", ".join(str(i) for i in v)))
        else:
            items.append((new_key, v))
    return dict(items)


def _collect_all_keys(records: list[dict]) -> list[str]:
    """Collect all unique keys across all records, preserving insertion order."""
    keys: dict[str, None] = {}
    for rec in records:
        for k in rec:
            keys[k] = None
    return list(keys.keys())


def export_excel(data: list[dict], output_path: str) -> str:
    """
    Export data to a formatted Excel file.

    Returns the path to the created file.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    flat_data = [_flatten_record(rec) for rec in data]
    columns = _collect_all_keys(flat_data)

    wb = Workbook()
    ws = wb.active
    ws.title = "Extracted Data"

    # Header styling
    header_font = Font(name="Inter", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin", color="333333"),
        right=Side(style="thin", color="333333"),
        top=Side(style="thin", color="333333"),
        bottom=Side(style="thin", color="333333"),
    )
    cell_font = Font(name="Inter", size=10)
    alt_fill = PatternFill(start_color="F5F5F5", end_color="F5F5F5", fill_type="solid")

    # Write headers
    for col_idx, col_name in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Write data rows
    for row_idx, record in enumerate(flat_data, 2):
        for col_idx, col_name in enumerate(columns, 1):
            value = record.get(col_name, "")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = cell_font
            cell.border = thin_border
            if row_idx % 2 == 0:
                cell.fill = alt_fill

    # Auto-fit column widths
    for col_idx, col_name in enumerate(columns, 1):
        max_len = len(str(col_name))
        for row_idx in range(2, min(len(flat_data) + 2, 100)):  # sample first 100 rows
            cell_val = ws.cell(row=row_idx, column=col_idx).value
            if cell_val:
                max_len = max(max_len, min(len(str(cell_val)), 60))
        ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 4

    # Freeze header row
    ws.freeze_panes = "A2"

    # Auto-filter
    ws.auto_filter.ref = ws.dimensions

    filepath = Path(output_path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if not filepath.suffix:
        filepath = filepath.with_suffix(".xlsx")

    wb.save(str(filepath))
    console.print(f"[green]Excel exported:[/] {filepath}  ({len(data)} rows)")
    return str(filepath)


def export_csv(data: list[dict], output_path: str) -> str:
    """
    Export data to a CSV file.

    Returns the path to the created file.
    """
    flat_data = [_flatten_record(rec) for rec in data]
    columns = _collect_all_keys(flat_data)

    filepath = Path(output_path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if not filepath.suffix:
        filepath = filepath.with_suffix(".csv")

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in flat_data:
            clean = {}
            for k, v in record.items():
                if isinstance(v, (dict, list)):
                    clean[k] = json.dumps(v, ensure_ascii=False)
                else:
                    clean[k] = v
            writer.writerow(clean)

    console.print(f"[green]CSV exported:[/] {filepath}  ({len(data)} rows)")
    return str(filepath)


def export_json(data: list[dict], output_path: str) -> str:
    """
    Export data to a pretty-printed JSON file.

    Returns the path to the created file.
    """
    filepath = Path(output_path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if not filepath.suffix:
        filepath = filepath.with_suffix(".json")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    console.print(f"[green]JSON exported:[/] {filepath}  ({len(data)} records)")
    return str(filepath)


def export(data: list[dict], fmt: str = "excel", output_path: str = "output/data") -> str:
    """
    Export extracted data to the specified format.

    Args:
        data: List of dicts to export.
        fmt: Format — 'excel', 'csv', or 'json'.
        output_path: Output file path (without extension).

    Returns:
        Path to the created file.
    """
    if not data:
        console.print("[yellow]No data to export.[/]")
        return ""

    fmt = fmt.lower().strip()

    if fmt == "excel" or fmt == "xlsx":
        return export_excel(data, output_path)
    elif fmt == "csv":
        return export_csv(data, output_path)
    elif fmt == "json":
        return export_json(data, output_path)
    else:
        console.print(f"[red]Unknown format '{fmt}'. Using JSON.[/]")
        return export_json(data, output_path)
