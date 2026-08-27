"""
Template context processors - small global flags available in every template.
"""

from sales_project.decorators import is_app_owner


def app_flags(request):
    """Expose IS_APP_OWNER so templates can hide owner-only features."""
    return {'IS_APP_OWNER': is_app_owner(getattr(request, 'user', None))}
