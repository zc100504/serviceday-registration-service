import logging
logger = logging.getLogger(__name__)


class SecurityMiddleware:
    """
    Topic 7.1a — Adds security headers to every response.
    Topic 7.2  — Logs unauthorized and forbidden access attempts.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Log incoming request
        user = request.user
        display = user.username if user.is_authenticated else "anonymous"
        logger.info(f"[REQUEST]  {request.method} {request.path} — user: {display}")

        response = self.get_response(request)

        # ── Security Headers (Topic 7.1a) ──────────────────
        response['X-XSS-Protection']       = '1; mode=block'
        response['X-Content-Type-Options']  = 'nosniff'
        response['X-Frame-Options']         = 'DENY'
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:;"
        )

        # ── Unauthorized Access Logging (Topic 7.2) ────────
        if response.status_code == 401:
            logger.warning(
                f"[UNAUTHORIZED] {request.method} {request.path} "
                f"— IP: {self.get_client_ip(request)}"
            )

        if response.status_code == 403:
            logger.warning(
                f"[FORBIDDEN] {request.method} {request.path} "
                f"— user: {display} — IP: {self.get_client_ip(request)}"
            )

        logger.info(f"[RESPONSE] {request.path} — status: {response.status_code}")

        return response

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')