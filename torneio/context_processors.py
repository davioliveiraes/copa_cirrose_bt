from django.conf import settings


def app_base_path(request):
    return {
        'app_base_path': settings.FORCE_SCRIPT_NAME or '',
    }
