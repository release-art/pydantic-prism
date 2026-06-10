"""``python -m pydantic_prism`` — equivalent to the ``prism`` console script."""

from ._codegen import main

raise SystemExit(main())
