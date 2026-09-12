"""Local dev entry point.

    python run.py            # http://localhost:8000
    python run.py --seed     # seed demo contacts first
"""

import sys

import uvicorn


def main() -> None:
    if "--seed" in sys.argv:
        from sales_fastapi.seed import seed

        seed()
    uvicorn.run("sales_fastapi.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
