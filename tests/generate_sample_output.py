"""Write a sample output folder using the offline fake Claude (no API key needed).

    python tests/generate_sample_output.py [input_dir] [output_dir]

The files show the exact output format. They were NOT produced by the live model;
run `python -m recon_claude` with ANTHROPIC_API_KEY set for real output.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from fake_claude import FakeClaude  # noqa: E402
from recon_claude.config import ReconConfig  # noqa: E402
from recon_claude.extraction import extract_all  # noqa: E402
from recon_claude.pipeline import discover_sources, run_reconciliation  # noqa: E402

config = ReconConfig.from_file(ROOT / "config.json")
sample = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "sample-data"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "output"
fake = FakeClaude(config.tolerances)
fake.reference, _ = extract_all(fake, discover_sources(config, sample)[0], config)
fake.usage["calls"] = 0
run_reconciliation(config, sample, out, llm=fake)
(out / "NOTE.txt").write_text(
    "Sample output generated offline with tests/fake_claude.py (model 'fake-claude'), not by\n"
    "claude-sonnet-5-5--VNGC. It shows the output format only. Re-run `python -m recon_claude` with\n"
    "the Azure SPN credentials set to overwrite this folder with real Claude-generated output.\n",
    encoding="utf-8")
