"""Allow ``python -m qts.cli`` as well as the ``qts`` console script."""

from qts.cli.main import main

if __name__ == "__main__":
    main()
