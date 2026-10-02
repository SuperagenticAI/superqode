"""Small public SDK example. Offline unless --provider and --model are supplied."""

import argparse
import asyncio
from pathlib import Path

from superqode.pipy import CodingSessionOptions, PiPyCodingSession, Model
from superqode.pipy.ai import FakeStream, text_response


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--session-root", type=Path, required=True)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--prompt", default="Summarise this repository.")
    args = parser.parse_args()
    if bool(args.provider) != bool(args.model):
        parser.error("Supply both --provider and --model")
    options = CodingSessionOptions(
        cwd=args.cwd,
        session_root=args.session_root,
        model=Model(id=args.model or "offline", provider=args.provider or "fixture"),
        stream_fn=None
        if args.provider
        else FakeStream([text_response("Offline SDK example completed.")]),
    )
    session = await PiPyCodingSession.create(options)
    response = await session.prompt(args.prompt)
    print(response.text)
    print(f"Session: {session.session_path}")


if __name__ == "__main__":
    asyncio.run(main())
