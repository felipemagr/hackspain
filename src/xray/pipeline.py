"""Run the whole pipeline: raw CSVs to the monthly panel."""

from xray import clean, panel


def main() -> None:
    """Clean the raw tables, then build the panels."""
    clean.main()
    panel.main()


if __name__ == "__main__":
    main()
