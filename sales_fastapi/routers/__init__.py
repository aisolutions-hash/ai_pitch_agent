from .auth import router as auth_router
from .contacts import router as contacts_router
from .email import router as email_router
from .social import router as social_router
from .system import router as system_router

__all__ = ["auth_router", "contacts_router", "email_router", "social_router", "system_router"]
