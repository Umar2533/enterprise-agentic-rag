from typing import Any, Dict


def ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, **data}

