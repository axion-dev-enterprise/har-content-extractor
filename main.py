"""
HAR Content Extractor — CLI Entry Point

Usage:
    python main.py --har site.har --goal "extrair produtos" --format excel
    python main.py --har site.har --analyze-only
    python main.py --har site.har --goal "imagens em alta resolução" --download-assets
"""

from __future__ import annotations

import argparse
import sys
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from har_parser import parse_har, print_profile
from ai_analyzer import analyze_site, analyze_only
from extractor import extract
from exporter import export

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="HAR Content Extractor — Extração inteligente de conteúdo via análise de HAR com IA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py --har site.har --goal "extrair todos os produtos com nome, preço e imagem" --format excel
  python main.py --har site.har --goal "extrair artigos do blog" --format csv
  python main.py --har site.har --goal "baixar imagens em alta resolução" --download-assets
  python main.py --har site.har --analyze-only
        """,
    )

    parser.add_argument("--har", required=True, help="Caminho para o arquivo .har")
    parser.add_argument("--goal", help="O que extrair (linguagem natural)")
    parser.add_argument("--format", default="excel", choices=["excel", "csv", "json"], help="Formato de saída (padrão: excel)")
    parser.add_argument("--output", default="output", help="Diretório de saída (padrão: ./output)")
    parser.add_argument("--analyze-only", action="store_true", help="Apenas analisar o site, sem extrair")
    parser.add_argument("--download-assets", action="store_true", help="Baixar imagens/arquivos referenciados")
    parser.add_argument("--replay-headers", action="store_true", help="Reutilizar headers capturados no HAR (cookies, auth)")
    parser.add_argument("--max-pages", type=int, default=50, help="Máximo de páginas a percorrer (padrão: 50)")
    parser.add_argument("--concurrency", type=int, default=3, help="Requisições simultâneas (padrão: 3)")
    parser.add_argument("--verbose", action="store_true", help="Log detalhado")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold]HAR Content Extractor[/]\n"
        "[dim]Extração inteligente via análise de HAR com IA[/]",
        border_style="blue",
    ))

    # 1. Parse HAR
    try:
        profile = parse_har(args.har)
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/] {e}")
        return 1
    except ValueError as e:
        console.print(f"[bold red]Error:[/] {e}")
        return 1

    print_profile(profile)

    # 2. Analyze-only mode
    if args.analyze_only:
        console.print("\n[bold blue]Running analysis-only mode...[/]")
        try:
            analysis = analyze_only(profile)
            console.print(Panel(analysis, title="Site Analysis", border_style="green"))

            # Save analysis
            out_path = Path(args.output)
            out_path.mkdir(parents=True, exist_ok=True)
            analysis_file = out_path / "site_analysis.md"
            analysis_file.write_text(analysis, encoding="utf-8")
            console.print(f"[dim]Analysis saved to {analysis_file}[/]")
        except Exception as e:
            console.print(f"[bold red]AI analysis failed:[/] {e}")
            return 1
        return 0

    # 3. Full extraction mode
    if not args.goal:
        console.print("[bold red]Error:[/] --goal is required (unless using --analyze-only)")
        console.print("[dim]Example: --goal \"extrair todos os produtos com nome, preço e imagem\"[/]")
        return 1

    # Get replay headers if requested
    replay_headers = None
    if args.replay_headers and profile.request_headers_sample:
        replay_headers = profile.request_headers_sample
        console.print(f"[dim]Replaying {len(replay_headers)} captured headers[/]")

    # AI analysis
    try:
        plan = analyze_site(profile, args.goal)
    except Exception as e:
        console.print(f"[bold red]AI analysis failed:[/] {e}")
        return 1

    if not plan.steps:
        console.print("[yellow]AI did not generate extraction steps. Check your goal or HAR file.[/]")
        if plan.raw_ai_response:
            console.print(Panel(plan.raw_ai_response[:2000], title="AI Response", border_style="yellow"))
        return 1

    # Save plan for reference
    out_path = Path(args.output)
    out_path.mkdir(parents=True, exist_ok=True)
    plan_file = out_path / "extraction_plan.json"
    plan_file.write_text(json.dumps({
        "site_summary": plan.site_summary,
        "architecture": plan.architecture,
        "strategy": plan.strategy,
        "steps": [
            {
                "description": s.description,
                "method": s.method,
                "url_template": s.url_template,
                "pagination": s.pagination,
                "data_path": s.data_path,
                "fields": s.fields,
            }
            for s in plan.steps
        ],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    # Execute extraction
    try:
        results = extract(
            plan,
            output_dir=args.output,
            max_pages=args.max_pages,
            concurrency=args.concurrency,
            replay_headers=replay_headers,
            download_assets_flag=args.download_assets,
        )
    except Exception as e:
        console.print(f"[bold red]Extraction failed:[/] {e}")
        return 1

    if not results:
        console.print("[yellow]No data extracted. The site may require authentication or the HAR file needs more pages captured.[/]")
        return 1

    # Export
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = str(out_path / f"extracted_{timestamp}")

    try:
        filepath = export(results, fmt=args.format, output_path=output_file)
    except Exception as e:
        console.print(f"[bold red]Export failed:[/] {e}")
        return 1

    console.print(Panel.fit(
        f"[bold green]Extraction complete![/]\n"
        f"Records: [cyan]{len(results)}[/]\n"
        f"Output: [cyan]{filepath}[/]\n"
        f"Plan: [dim]{plan_file}[/]",
        border_style="green",
    ))

    return 0


if __name__ == "__main__":
    sys.exit(main())
