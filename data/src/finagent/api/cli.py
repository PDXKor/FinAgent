import argparse

import uvicorn

from finagent.api.app import create_app
from finagent.api.config import ApiSettings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="finagent-data", description="FinAgentData HTTP API.")
    sub = p.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    args = p.parse_args(argv)

    settings = ApiSettings()
    uvicorn.run(
        create_app(settings),
        host=args.host or settings.api_host,
        port=args.port or settings.api_port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
