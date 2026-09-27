import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path to enable absolute imports
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.main import create_app


def export_openapi(
    is_mock: bool = True, output_path: Path | None = None
) -> Path:
    """Exports OpenAPI schema from the FastAPI application factory."""
    if output_path is None:
        output_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "contracts"
            / "openapi.json"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    app = create_app(is_mock=is_mock)
    openapi_schema = app.openapi()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)

    total_paths = len(openapi_schema.get("paths", {}))
    mode_str = "MOCK" if is_mock else "PRODUCTION"
    print(
        f"[OK] OpenAPI schema ({mode_str} mode, {total_paths} paths) successfully exported to:\n     {output_path}"
    )
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export OpenAPI JSON schema for client code generation (NSwag / OpenAPI Generator)."
    )
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Export production schema (excludes mock-only administration endpoints).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Target output file path (defaults to docs/contracts/openapi.json).",
    )
    args = parser.parse_args()

    is_mock = not args.prod
    export_openapi(is_mock=is_mock, output_path=args.output)
