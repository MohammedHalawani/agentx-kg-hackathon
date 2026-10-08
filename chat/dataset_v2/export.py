"""Offline CLI: validate before publishing a deterministic versioned export."""
import argparse
from pathlib import Path
import tempfile

from dataset_v2.contracts import Config, World, canonical
from dataset_v2.generate import generate
from dataset_v2.validate import validate_world


def export_world(world: World, destination: Path | str) -> dict:
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Choose a new export directory; existing exports are immutable")
    validation=validate_world(world)
    if not validation["pass"]:
        codes=sorted({error["code"] for error in validation["errors"]})
        raise ValueError(f"World failed domain validation: {codes}")
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Atomic directory rename: interrupted preparation cannot masquerade as a bundle.
    with tempfile.TemporaryDirectory(prefix=".v2-stage-",dir=destination.parent) as directory:
        stage=Path(directory)/"bundle"
        stage.mkdir()
        for name,records in (("nodes",(world.nodes[key].record() for key in sorted(world.nodes))),
                             ("edges",(world.edges[key].record() for key in sorted(world.edges))),
                             ("gold",(world.gold[key] for key in sorted(world.gold)))):
            with (stage/f"{name}.jsonl").open("w",encoding="utf-8",newline="\n") as stream:
                for row in records:
                    stream.write(canonical(row)+"\n")
        for name,value in (("manifest",world.manifest()),("validation",validation),
                           ("statistics",validation["statistics"])):
            (stage/f"{name}.json").write_text(canonical(value)+"\n",encoding="utf-8",newline="\n")
        stage.rename(destination)
    return validation


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("../artifacts/dataset-v2/main"))
    for name in ("total","history","development","held-out","seed","simulation-days","reconciliation-grace-minutes"):
        parser.add_argument(f"--{name}",type=int,default=2000 if name=="total" else 42 if name=="seed" else 40 if name=="simulation-days" else 60 if name=="reconciliation-grace-minutes" else None)
    parser.add_argument("--normal-fraction",type=float,default=.70)
    parser.add_argument("--start-at",default="2026-09-01T00:00:00+00:00")
    parser.add_argument("--session-start",default="06:00")
    parser.add_argument("--session-end",default="16:00")
    args=vars(parser.parse_args(argv))
    output=args.pop("output")
    validation=export_world(generate(Config(**args)),output)
    print(canonical({"status":"offline_export_validated","output":str(output.resolve()),
                     "statistics":validation["statistics"]}))


if __name__=="__main__":
    main()
