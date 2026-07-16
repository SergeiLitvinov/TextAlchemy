import argparse


def cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    from textalchemy.web import app
    print(f"Starting TextAlchemy web at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0
