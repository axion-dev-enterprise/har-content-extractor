"""
AI Analyzer — Uses an LLM to analyze the site profile and generate an extraction plan.

Compatible with any OpenAI-compatible API (OpenRouter, OpenAI, Google AI Studio, etc.).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from rich.console import Console

from har_parser import SiteProfile

load_dotenv()
console = Console()

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class ExtractionStep:
    """A single step in the extraction plan."""
    description: str
    method: str  # GET, POST
    url_template: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] | None = None
    pagination: dict[str, Any] | None = None  # {"type": "page"|"offset"|"cursor", "param": "...", "start": 1, "step": 1, "max": 50}
    data_path: str = ""  # JSONPath-like key to extract data from response (e.g. "data.products")
    fields: list[str] = field(default_factory=list)  # Fields to extract from each item


@dataclass
class ExtractionPlan:
    """Complete plan for extracting data from a site."""
    site_summary: str = ""
    architecture: str = ""
    strategy: str = ""
    steps: list[ExtractionStep] = field(default_factory=list)
    auth_required: bool = False
    auth_notes: str = ""
    raw_ai_response: str = ""


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_path = PROMPTS_DIR / name
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def _build_analysis_messages(profile: SiteProfile, user_goal: str) -> list[dict]:
    """Build the message payload for the AI."""
    base_prompt = _load_prompt("base_prompt.txt")
    extraction_prompt = _load_prompt("extraction_prompt.txt")

    profile_json = json.dumps(profile.to_dict(), indent=2, ensure_ascii=False)

    # Find sample response bodies from API endpoints
    sample_responses = []
    for ep in profile.api_endpoints[:10]:
        if ep.response_body_preview:
            sample_responses.append({
                "endpoint": f"{ep.method} {ep.path}",
                "content_type": ep.response_content_type,
                "preview": ep.response_body_preview[:1000],
            })

    user_message = extraction_prompt.replace("{goal}", user_goal)
    user_message = user_message.replace("{site_profile}", profile_json)
    user_message = user_message.replace("{sample_responses}", json.dumps(sample_responses, indent=2, ensure_ascii=False))

    return [
        {"role": "system", "content": base_prompt},
        {"role": "user", "content": user_message},
    ]


def _parse_ai_response(response_text: str) -> ExtractionPlan:
    """Parse the AI's JSON response into an ExtractionPlan."""
    # Extract JSON from markdown code fences if present
    text = response_text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
        text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        text = text.split("```", 1)[0]

    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        console.print("[bold red]Failed to parse AI response as JSON. Returning raw.[/]")
        plan = ExtractionPlan(raw_ai_response=response_text)
        return plan

    plan = ExtractionPlan(
        site_summary=data.get("site_summary", ""),
        architecture=data.get("architecture", ""),
        strategy=data.get("strategy", ""),
        auth_required=data.get("auth_required", False),
        auth_notes=data.get("auth_notes", ""),
        raw_ai_response=response_text,
    )

    for step_data in data.get("steps", []):
        step = ExtractionStep(
            description=step_data.get("description", ""),
            method=step_data.get("method", "GET").upper(),
            url_template=step_data.get("url_template", step_data.get("url", "")),
            headers=step_data.get("headers", {}),
            params=step_data.get("params", {}),
            body=step_data.get("body"),
            pagination=step_data.get("pagination"),
            data_path=step_data.get("data_path", ""),
            fields=step_data.get("fields", []),
        )
        plan.steps.append(step)

    return plan


def analyze_site(profile: SiteProfile, user_goal: str) -> ExtractionPlan:
    """
    Send the site profile to the AI and get an extraction plan.

    Args:
        profile: Structured site profile from HAR parsing.
        user_goal: What the user wants to extract (natural language).

    Returns:
        ExtractionPlan with steps to execute.
    """
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.getenv("AI_MODEL", "google/gemini-2.5-flash")

    if not api_key:
        raise ValueError("AI_API_KEY not set. Copy .env.example to .env and add your key.")

    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = _build_analysis_messages(profile, user_goal)

    console.print(f"\n[bold blue]Sending to AI:[/] {model}")
    console.print(f"[dim]Base URL: {base_url}[/]")

    with console.status("[bold green]AI is analyzing the site architecture..."):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=8000,
        )

    ai_text = response.choices[0].message.content or ""

    console.print("[green]AI analysis complete.[/]")

    plan = _parse_ai_response(ai_text)

    # Print summary
    if plan.site_summary:
        console.print(f"\n[bold]Site Summary:[/] {plan.site_summary}")
    if plan.architecture:
        console.print(f"[bold]Architecture:[/] {plan.architecture}")
    if plan.strategy:
        console.print(f"[bold]Strategy:[/] {plan.strategy}")
    if plan.auth_required:
        console.print(f"[bold yellow]Auth Required:[/] {plan.auth_notes}")
    console.print(f"[bold]Extraction Steps:[/] {len(plan.steps)}")

    for i, step in enumerate(plan.steps, 1):
        console.print(f"  {i}. [cyan]{step.method}[/] {step.url_template[:80]}")
        if step.pagination:
            console.print(f"     [dim]Pagination: {step.pagination}[/]")

    return plan


def analyze_only(profile: SiteProfile) -> str:
    """
    Run AI analysis without extraction goal — just describe the site architecture.

    Returns the AI's raw analysis text.
    """
    api_key = os.getenv("AI_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.getenv("AI_MODEL", "google/gemini-2.5-flash")

    if not api_key:
        raise ValueError("AI_API_KEY not set. Copy .env.example to .env and add your key.")

    client = OpenAI(api_key=api_key, base_url=base_url)
    base_prompt = _load_prompt("base_prompt.txt")
    profile_json = json.dumps(profile.to_dict(), indent=2, ensure_ascii=False)

    messages = [
        {"role": "system", "content": base_prompt},
        {
            "role": "user",
            "content": (
                "Analyze this site profile from a HAR capture and provide a detailed "
                "technical breakdown of the site architecture, content delivery patterns, "
                "API structure, and recommended extraction strategies.\n\n"
                f"Site Profile:\n```json\n{profile_json}\n```"
            ),
        },
    ]

    with console.status("[bold green]AI is analyzing the site..."):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=4000,
        )

    return response.choices[0].message.content or ""
