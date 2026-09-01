"""Regenerate the redistributable rectangular cantilever STEP fixture."""

from pathlib import Path

from build123d import Align, Box, export_step

LENGTH_MM = 200.0
WIDTH_MM = 20.0
HEIGHT_MM = 40.0
OUTPUT = Path(__file__).with_name("cantilever.step")


def main() -> None:
    beam = Box(
        LENGTH_MM,
        WIDTH_MM,
        HEIGHT_MM,
        align=(Align.MIN, Align.CENTER, Align.CENTER),
    )
    beam.label = "CantileverBeam"
    export_step(beam, OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
