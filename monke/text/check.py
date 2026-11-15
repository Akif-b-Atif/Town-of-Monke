"""python -m monke.text.check [path]: validate a flavour file and list every problem with its key and line."""
import pathlib
import sys

from .bank import load_text


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = pathlib.Path(argv[0]) if argv else pathlib.Path("flavour.yaml")
    bank, rep = load_text(path)
    for p in rep.errors:
        print("ERROR  ", p)
    for p in rep.warnings:
        print("warning", p)
    print(f"{path}: {rep.keys} keys, {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
