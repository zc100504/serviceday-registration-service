import logging
logger = logging.getLogger(__name__)


class SecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ← fix: handle dict user (StatelessJWT)
        user = request.user
        if isinstance(user, dict):
            display = user.get('username', 'unknown')
        elif hasattr(user, 'is_authenticated') and user.is_authenticated:
            display = user.username
        else:
            display = 'anonymous'

        logger.info(f"[REQUEST]  {request.method} {request.path} — user: {display}")

        response = self.get_response(request)

        response['X-XSS-Protection']       = '1; mode=block'
        response['X-Content-Type-Options']  = 'nosniff'
        response['X-Frame-Options']         = 'DENY'
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://cdn.jsdelivr.net;"
        )

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