from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class UploadTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, "Upload request is too large. Split the file and retry.")


class UploadLimitMiddleware:
    """Bound the multipart request before Starlette can spool an unbounded upload."""

    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].endswith(("/documents", "/vaults/import", "/sync"))
        ):
            await self.app(scope, receive, send)
            return
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise UploadTooLarge()
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except UploadTooLarge:
            await JSONResponse(
                {"detail": "Upload request is too large. Split the file and retry."}, status_code=413
            )(scope, receive, send)
