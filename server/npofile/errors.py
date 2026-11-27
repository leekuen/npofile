from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    """統一錯誤格式：{"error": {"code": ..., "message": ..., "fields": {...}}}"""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    fields = {}
    message = ""
    if isinstance(data, dict):
        detail = data.get("detail")
        if detail is not None:
            message = str(detail)
        fields = {k: [str(m) for m in (v if isinstance(v, list) else [v])] for k, v in data.items() if k != "detail"}
        if not message and fields:
            message = next(iter(fields.values()))[0]
    elif isinstance(data, list):
        message = str(data[0]) if data else ""
    code = getattr(exc, "default_code", "error")
    response.data = {"error": {"code": code, "message": message, "fields": fields}}
    return response
