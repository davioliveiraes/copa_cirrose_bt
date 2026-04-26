from django.conf import settings


def app_base_path(request):
    prefix = settings.URL_PATH_PREFIX
    return {
        'app_base_path': f'/{prefix}' if prefix else '',
    }
