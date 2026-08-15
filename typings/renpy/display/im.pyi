from typing import Any

class Image:
    def __init__(self, filename: str, **properties: Any) -> None: ...

class MatrixColor:
    def __init__(self, image: Any, matrix: Any, **properties: Any) -> None: ...

class matrix:
    @staticmethod
    def colorize(black_color: Any, white_color: Any) -> Any: ...
