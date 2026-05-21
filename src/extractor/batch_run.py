"""Full extraction run across all tickers.

Usage:
    python -m extractor.batch_run

Runs extraction on ~20 calls per ticker (2020-2025), saves JSON + CSV
per call, and writes a manifest at data/extraction_runs/manifest.json.
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

from extractor.extract import deduplicate, enrich_result, filter_vague
from extractor.loader import TranscriptLoader
from extractor.output import write_csv, write_json
from extractor.prompts import SYSTEM_PROMPT, build_user_prompt
from extractor.schema import ExtractionResult, _ClaimsWrapper

TICKERS = ["AMZN", "TSLA", "KO", "LLY"]
PARQUET_PATTERN = "Pulled_data/{ticker}/transcript/{ticker}_transcripts.parquet"
OUT_DIR = Path("data/extraction_runs")
MAX_CALLS_PER_TICKER = 20
START_DATE = date(2020, 1, 1)
END_DATE = date(2025, 12, 31)
SLEEP_BETWEEN_CALLS = 1  # seconds, avoids rate limits
MAX_TRANSCRIPT_CHARS = 30_000  # ~7,500 tokens — keeps prepared remarks, fits in model context


def _extract_one(ticker: str, transcript_id: int, call_date: date, text: str) -> ExtractionResult:
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


def run_ticker(ticker: str) -> list[dict]:
    parquet = Path(PARQUET_PATTERN.format(ticker=ticker))
    if not parquet.exists():
        print(f"  [SKIP] {parquet} not found")
        return []

    loader = TranscriptLoader(parquet)
    calls = loader.list_calls()

    # Filter to 2020–2025 and pick one transcript_id per unique call date
    calls["date_only"] = calls["mostimportantdateutc"].astype(str).str[:10]
    calls = calls[calls["date_only"] >= str(START_DATE)]
    calls = calls[calls["date_only"] <= str(END_DATE)]
    calls = calls.drop_duplicates(subset=["date_only"]).head(MAX_CALLS_PER_TICKER)

    print(f"\n{'='*60}")
    print(f"  {ticker}: {len(calls)} calls to extract")
    print(f"{'='*60}")

    entries = []
    total_claims = 0

    for _, row in calls.iterrows():
        tid = int(row["transcriptid"])
        call_date = date.fromisoformat(row["date_only"])
        out_json = OUT_DIR / f"{ticker}_{row['date_only']}.json"
        out_csv  = OUT_DIR / f"{ticker}_{row['date_only']}.csv"

        # Skip if already done
        if out_json.exists():
            try:
                existing = json.loads(out_json.read_text())
                n = len(existing.get("claims", []))
                print(f"  [SKIP] {ticker} {row['date_only']} — already extracted ({n} claims)")
                entries.append({"path": str(out_json), "ticker": ticker,
                                "call_date": row["date_only"], "n_claims": n})
                total_claims += n
                continue
            except Exception:
                pass

        try:
            text = loader.get_transcript(tid)[:MAX_TRANSCRIPT_CHARS]
            raw = _extract_one(ticker, tid, call_date, text)
            result = deduplicate(filter_vague(raw))
            transcript_df = loader._df[loader._df["transcriptid"] == tid]
            enriched = enrich_result(result, transcript_df)

            OUT_DIR.mkdir(parents=True, exist_ok=True)
            write_json(enriched, out_json)
            write_csv(enriched, out_csv)

            n = len(enriched["claims"])
            total_claims += n
            entries.append({"path": str(out_json), "ticker": ticker,
                            "call_date": row["date_only"], "n_claims": n})
            print(f"  [OK]   {ticker} {row['date_only']} — {n} claims")
            time.sleep(SLEEP_BETWEEN_CALLS)

        except Exception as e:
            print(f"  [FAIL] {ticker} {row['date_only']} — {e}")
            traceback.print_exc()
            entries.append({"path": str(out_json), "ticker": ticker,
                            "call_date": row["date_only"], "n_claims": 0, "error": str(e)})

    print(f"\n  {ticker} done: {len(calls)} calls, {total_claims} total claims")
    return entries


def main() -> None:
    load_dotenv()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_entries = []
    grand_total = 0

    for ticker in TICKERS:
        entries = run_ticker(ticker)
        all_entries.extend(entries)
        grand_total += sum(e.get("n_claims", 0) for e in entries)

    manifest = {
        "generated_at": datetime.now().isoformat(),
        "total_claims": grand_total,
        "total_calls": len(all_entries),
        "files": all_entries,
    }
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n{'='*60}")
    print(f"  DONE: {len(all_entries)} calls, {grand_total} total claims")
    print(f"  Manifest -> {manifest_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
