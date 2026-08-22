from __future__ import annotations

"""Public R6O-2 terminal View entry point."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r6o.views.tui import TuiApplication, TuiController
from scripts._r6o2_recorded import start_recorded_session


def _viewport(value: str) -> tuple[int, int]:
    try:
        width, height = (int(item) for item in value.lower().split("x", 1))
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("viewport must be WIDTHxHEIGHT") from None
    if width < 42 or height < 14:
        raise argparse.ArgumentTypeError("viewport must be at least 42x14")
    return width, height


def _capture_screen(screen: str, destination: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = None
    for candidate in (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "CascadiaMono.ttf",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "consola.ttf",
    ):
        if candidate.is_file():
            font = ImageFont.truetype(str(candidate), 18)
            break
    font = font or ImageFont.load_default()
    lines = screen.splitlines()
    box = font.getbbox("M")
    cell_width = max(8, box[2] - box[0])
    cell_height = max(16, box[3] - box[1] + 6)
    image = Image.new(
        "RGB",
        (max(len(line) for line in lines) * cell_width + 28, len(lines) * cell_height + 28),
        "#080f18",
    )
    draw = ImageDraw.Draw(image)
    draw.multiline_text((14, 14), screen, font=font, fill="#e6edf6", spacing=6)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the public R6O-2 TUI")
    parser.add_argument("--recorded", action="store_true", help="use a deterministic recorded binding")
    parser.add_argument("--case", choices=("G06", "A02"), default="G06")
    parser.add_argument("--capture", type=Path, help="capture the initial public screen and exit")
    parser.add_argument(
        "--capture-stage",
        choices=("PROMPT_REVIEW", "PLAN_REVIEW"),
        default="PROMPT_REVIEW",
    )
    parser.add_argument("--viewport", type=_viewport, default=(100, 30), help="capture/smoke viewport WIDTHxHEIGHT")
    parser.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.recorded:
        parser.error("--recorded is required for the H2 public surface")

    if args.case != "G06" and args.capture_stage == "PLAN_REVIEW":
        parser.error("--capture-stage PLAN_REVIEW requires --case G06")

    session = start_recorded_session(args.case, surface=f"r6o2-tui-{args.case.lower()}")
    try:
        controller = TuiController(
            session.adapter,
            session.session_id,
            qualification_case=args.case,
        )
        smoke = args.smoke or os.environ.get("R6O2_SMOKE_MODE") == "1"
        if smoke or args.capture:
            if args.capture_stage == "PLAN_REVIEW":
                controller.select_action()
            screen = controller.render(*args.viewport)
            if args.capture:
                _capture_screen(screen, args.capture)
            print(
                "R6O2_TUI_READY "
                f"session={controller.projection['session_id']} "
                f"stage={controller.projection['stage']} "
                f"case={args.case} event_loop={TuiApplication.__name__}"
            )
            return 0
        TuiApplication(controller).run()
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
