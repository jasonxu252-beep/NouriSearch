"""Writes the API's OpenAPI document, which the frontend's typed client is generated from.

python -m app.export_openapi ../frontend/openapi.json
"""

import json
import sys
from pathlib import Path

from app.main import create_app


def main(argv: list[str] | None = None) -> int:
    target = Path((argv if argv is not None else sys.argv[1:])[0])
    document = create_app().openapi()
    target.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
