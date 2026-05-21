"""CLI: python -m extractor.run --parquet PATH --ticker TICKER [--list | --transcript-id ID]"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from extractor.extract import deduplicate, enrich_result
from extractor.loader import TranscriptLoader
from extractor.output import write_csv, write_json
from extractor.prompts import SYSTEM_PROMPT, build_user_prompt
from extractor.schema import ExtractionResult, _ClaimsWrapper


def _extract(ticker: str, transcript_id: int, call_date: date, text: str) -> ExtractionResult:
    import openai

    client = openai.OpenAI()
    response = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(text, ticker)},
        ],
        response_format=_ClaimsWrapper,
        temperature=0,
    )
    wrapper = response.choices[0].message.parsed
    return ExtractionResult(
        ticker=ticker,
        transcript_id=transcript_id,
        call_date=call_date,
        claims=[c.to_typed() for c in wrapper.claims],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extractor.run", description=__doc__)
    parser.add_argument("--parquet", required=True, type=Path)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--list", action="store_true", help="List available calls and exit.")
    parser.add_argument("--transcript-id", type=int)
    parser.add_argument("--print-input", action="store_true",
                        help="Print assembled transcript to stderr before extraction.")
    parser.add_argument("--out", type=Path, help="Save enriched JSON to this path.")
    parser.add_argument("--csv", type=Path, help="Also save a CSV to this path.")
    args = parser.parse_args(argv)

    load_dotenv()
    loader = TranscriptLoader(args.parquet)

    if args.list:
        calls = loader.list_calls()
        print(calls.to_string(index=False))
        return 0

    if not args.transcript_id:
        parser.error("--transcript-id is required when not using --list")

    calls = loader.list_calls()
    row = calls[calls["transcriptid"] == args.transcript_id]
    if row.empty:
        print(f"Error: transcript_id {args.transcript_id} not found", file=sys.stderr)
        return 1
    call_date = date.fromisoformat(str(row.iloc[0]["mostimportantdateutc"])[:10])

    text = loader.get_transcript(args.transcript_id)
    if args.print_input:
        print(text, file=sys.stderr)

    raw = _extract(args.ticker.upper(), args.transcript_id, call_date, text)
    result = deduplicate(raw)

    # Load the raw transcript DataFrame for provenance enrichment
    transcript_df = loader._df[loader._df["transcriptid"] == args.transcript_id]
    enriched = enrich_result(result, transcript_df)

    n = len(enriched["claims"])

    if args.out:
        write_json(enriched, args.out)
        print(f"Saved {n} claims (JSON) -> {args.out}")
    else:
        import json
        print(json.dumps(enriched, indent=2))

    if args.csv:
        write_csv(enriched, args.csv)
        print(f"Saved {n} claims (CSV)  -> {args.csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
