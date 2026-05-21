"""CLI: python -m extractor.run --parquet PATH --ticker TICKER [--list | --transcript-id ID]"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from extractor.loader import TranscriptLoader
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
    parser.add_argument("--out", type=Path, help="Save extraction JSON to this path.")
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

    result = _extract(args.ticker.upper(), args.transcript_id, call_date, text)

    output_json = result.model_dump_json(indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output_json, encoding="utf-8")
        print(f"Saved {len(result.claims)} claims to {args.out}")
    else:
        print(output_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
