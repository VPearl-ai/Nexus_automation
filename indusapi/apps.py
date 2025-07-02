from django.apps import AppConfig
from indusproject.scheduler import start_scheduler

class IndusapiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'indusapi'

    def ready(self):
        start_scheduler()
