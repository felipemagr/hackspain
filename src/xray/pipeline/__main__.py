"""Run the whole pipeline: raw CSVs to the monthly panel."""

from xray.pipeline import cash, clean, panel


def main() -> None:
    """Clean the raw tables, reconstruct cash, then build the panels."""
    clean.main()
    cash.main()
    panel.main()


if __name__ == "__main__":
    main()
