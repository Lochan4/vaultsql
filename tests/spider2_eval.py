"""
tests/spider2_eval.py

Spider 2.0-Lite evaluation script for the VaultSQL pipeline.

Runs the full NL→SQL pipeline on Spider 2.0-Lite examples and reports:
  - Valid SQL rate     (generated SQL executed without error)
  - Execution accuracy (generated results match gold results)
  - Complexity breakdown (Haiku / Sonnet routing distribution)
  - Per-example detail log (optional JSON output)

Usage:
    # Download Spider 2.0-Lite first:
    #   https://github.com/xlang-ai/spider2
    #   spider2-lite/spider2-lite.jsonl
    #   spider2-lite/resource/databases/{db_id}/{db_id}.sqlite

    python tests/spider2_eval.py \\
        --dataset  path/to/spider2-lite.jsonl \\
        --db-dir   path/to/spider2-lite/resource/databases \\
        --limit    100 \\
        --output   results.json

Requirements:
    pip install -e .   (VaultSQL itself — no extra packages needed)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

# ── VaultSQL core imports ─────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import anchor_extractor
from core import enrichment as enrichment_mod
from core import joinability
from core import pathfinder as pf_mod
from core.complexity_router import route
from core.executor import Executor
from core.generator import generate
from core.introspector import Introspector
from core.retriever import Retriever


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ExampleResult:
    instance_id: str
    question: str
    db_id: str
    gold_sql: str
    generated_sql: str = ""
    model_used: str = ""
    complexity: str = ""
    tables_used: list[str] = field(default_factory=list)
    valid_sql: bool = False          # generated SQL ran without error
    exec_match: bool = False         # results match gold
    error: str = ""
    latency_s: float = 0.0


# ── Dataset loader ────────────────────────────────────────────────────────────

def load_dataset(path: Path, limit: int | None) -> list[dict]:
    """
    Load Spider 2.0-Lite examples from a JSONL file.

    Expected fields per line:
        instance_id, db_id, question, gold_sql
    """
    examples = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line))
            if limit and len(examples) >= limit:
                break
    return examples


# ── Result comparator ─────────────────────────────────────────────────────────

def results_match(gold_df: pd.DataFrame, gen_df: pd.DataFrame) -> bool:
    """
    Compare two DataFrames for execution accuracy.

    Normalisation applied before comparison:
      - Column order ignored (sort columns alphabetically)
      - Row order ignored (sort all rows)
      - Values lowercased if string
      - Floats rounded to 4dp to absorb tiny precision differences
    """
    if gold_df.empty and gen_df.empty:
        return True
    if gold_df.shape != gen_df.shape:
        return False

    def normalise(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Lowercase column names
        df.columns = [str(c).lower() for c in df.columns]
        df = df.reindex(sorted(df.columns), axis=1)
        # Normalise cell values
        for col in df.columns:
            if pd.api.types.is_float_dtype(df[col]):
                df[col] = df[col].round(4)
            elif df[col].dtype == object:
                df[col] = df[col].astype(str).str.lower().str.strip()
        # Sort rows
        try:
            df = df.sort_values(by=list(df.columns)).reset_index(drop=True)
        except TypeError:
            df = df.astype(str).sort_values(by=list(df.columns)).reset_index(drop=True)
        return df

    try:
        return normalise(gold_df).equals(normalise(gen_df))
    except Exception:
        return False


# ── Single example pipeline ───────────────────────────────────────────────────

def run_example(
    question: str,
    db_path: Path,
    gold_sql: str,
    retriever: Retriever,
) -> tuple[str, str, str, list[str], bool, bool, str]:
    """
    Run the full VaultSQL pipeline for one Spider example.

    Returns:
        (generated_sql, model_used, complexity, tables_used,
         valid_sql, exec_match, error)
    """
    conn_str = f"sqlite:///{db_path}"
    empty_enrichment = enrichment_mod.load("__nonexistent__")  # always empty

    # 1. Introspect
    inspector = Introspector(conn_str)
    snapshot = inspector.run()
    inspector.close()
    snapshot = enrichment_mod.merge(snapshot, empty_enrichment)

    # 2. Anchor extraction
    anchors = anchor_extractor.extract(question, snapshot)

    # 3. Pathfinding
    pathfinder = pf_mod.Pathfinder(snapshot)
    path_result = pathfinder.find(anchors)

    # 4. Joinability (if FK missing)
    if path_result.has_missing_fk:
        path_result = joinability.infer_joins(path_result, snapshot)

    # 5. Complexity routing
    routing = route(question, path_result)

    # 6. Few-shot retrieval (empty for Spider — no prior verified queries)
    examples = retriever.find(question, top_k=3)

    # 7. SQL generation
    gen_result = generate(
        question=question,
        snapshot=snapshot,
        path_result=path_result,
        enrichment=empty_enrichment,
        examples=examples,
        model=routing.model,
        dialect=snapshot.dialect,
    )

    if not gen_result.sql:
        return ("", routing.model, routing.complexity.value, [], False, False,
                "SQL generation returned empty result")

    # 8. Execute generated SQL
    executor = Executor(conn_str)
    gen_exec = executor.run(gen_result.sql)

    if not gen_exec.success:
        executor.close()
        return (gen_result.sql, routing.model, routing.complexity.value,
                gen_result.tables_used, False, False, gen_exec.error)

    # 9. Execute gold SQL for comparison
    gold_exec = executor.run(gold_sql)
    executor.close()

    if not gold_exec.success:
        # Gold SQL failed — skip exec_match, count as valid SQL at least
        return (gen_result.sql, routing.model, routing.complexity.value,
                gen_result.tables_used, True, False,
                f"Gold SQL failed: {gold_exec.error}")

    match = results_match(gold_exec.data, gen_exec.data)

    return (gen_result.sql, routing.model, routing.complexity.value,
            gen_result.tables_used, True, match, "")


# ── Main evaluation loop ──────────────────────────────────────────────────────

def evaluate(
    dataset_path: Path,
    db_dir: Path,
    limit: int | None,
    output_path: Path | None,
) -> None:
    examples = load_dataset(dataset_path, limit)
    total = len(examples)
    print(f"\nLoaded {total} examples from {dataset_path.name}")
    print(f"Database directory: {db_dir}")
    print("-" * 60)

    # One shared retriever (no prior examples — cold start)
    retriever = Retriever()
    retriever.setup()

    results: list[ExampleResult] = []

    for i, ex in enumerate(examples, 1):
        instance_id = ex.get("instance_id", f"ex_{i}")
        db_id       = ex["db_id"]
        question    = ex["question"]
        gold_sql    = ex["gold_sql"]

        # Locate database file
        db_path = db_dir / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            # Try flat layout: db_dir/{db_id}.sqlite
            db_path = db_dir / f"{db_id}.sqlite"
        if not db_path.exists():
            result = ExampleResult(
                instance_id=instance_id,
                question=question,
                db_id=db_id,
                gold_sql=gold_sql,
                error=f"Database file not found: {db_id}",
            )
            results.append(result)
            _print_row(i, total, result)
            continue

        t0 = time.perf_counter()
        try:
            sql, model, complexity, tables, valid, match, err = run_example(
                question=question,
                db_path=db_path,
                gold_sql=gold_sql,
                retriever=retriever,
            )
            latency = time.perf_counter() - t0
            result = ExampleResult(
                instance_id=instance_id,
                question=question,
                db_id=db_id,
                gold_sql=gold_sql,
                generated_sql=sql,
                model_used=model,
                complexity=complexity,
                tables_used=tables,
                valid_sql=valid,
                exec_match=match,
                error=err,
                latency_s=round(latency, 2),
            )
        except Exception as exc:
            latency = time.perf_counter() - t0
            result = ExampleResult(
                instance_id=instance_id,
                question=question,
                db_id=db_id,
                gold_sql=gold_sql,
                error=str(exc),
                latency_s=round(latency, 2),
            )

        results.append(result)
        _print_row(i, total, result)

    _print_summary(results)

    if output_path:
        output_path.write_text(
            json.dumps([asdict(r) for r in results], indent=2)
        )
        print(f"\nDetailed results saved to: {output_path}")


# ── Reporting helpers ─────────────────────────────────────────────────────────

def _print_row(i: int, total: int, r: ExampleResult) -> None:
    valid  = "✓" if r.valid_sql  else "✗"
    match  = "✓" if r.exec_match else "✗"
    err    = f"  [{r.error[:60]}]" if r.error else ""
    print(
        f"[{i:>4}/{total}] valid={valid} match={match} "
        f"{r.complexity:<8} {r.latency_s:>5.1f}s  {r.instance_id}{err}"
    )


def _print_summary(results: list[ExampleResult]) -> None:
    total       = len(results)
    valid_count = sum(1 for r in results if r.valid_sql)
    match_count = sum(1 for r in results if r.exec_match)

    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"  Total examples    : {total}")
    print(f"  Valid SQL rate    : {valid_count}/{total}  ({_pct(valid_count, total)})")
    print(f"  Execution accuracy: {match_count}/{total}  ({_pct(match_count, total)})")

    # Complexity breakdown
    from collections import Counter
    complexity_counts = Counter(r.complexity for r in results if r.complexity)
    print("\n  Complexity distribution:")
    for tier, count in sorted(complexity_counts.items()):
        tier_results = [r for r in results if r.complexity == tier]
        tier_match   = sum(1 for r in tier_results if r.exec_match)
        print(f"    {tier:<10} {count:>4} examples  exec_acc={_pct(tier_match, count)}")

    # Model usage
    model_counts = Counter(r.model_used for r in results if r.model_used)
    print("\n  Model usage:")
    for model, count in model_counts.most_common():
        short = model.split("-")[1] if "-" in model else model
        print(f"    {short:<10} {count:>4} calls")

    # Error summary
    errors = [r for r in results if r.error]
    if errors:
        print(f"\n  Errors: {len(errors)} examples failed")
        error_types: Counter = Counter()
        for r in errors:
            key = r.error[:50]
            error_types[key] += 1
        for msg, count in error_types.most_common(5):
            print(f"    [{count:>3}x] {msg}")

    print("=" * 60)


def _pct(n: int, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{100 * n / total:.1f}%"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate VaultSQL pipeline on Spider 2.0-Lite"
    )
    parser.add_argument(
        "--dataset", required=True, type=Path,
        help="Path to spider2-lite.jsonl",
    )
    parser.add_argument(
        "--db-dir", required=True, type=Path,
        help="Directory containing Spider databases (each as {db_id}/{db_id}.sqlite)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max number of examples to evaluate (default: all)",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional path to write per-example JSON results",
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"ERROR: Dataset file not found: {args.dataset}")
        sys.exit(1)
    if not args.db_dir.exists():
        print(f"ERROR: Database directory not found: {args.db_dir}")
        sys.exit(1)

    evaluate(
        dataset_path=args.dataset,
        db_dir=args.db_dir,
        limit=args.limit,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
