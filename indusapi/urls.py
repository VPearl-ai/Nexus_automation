# indus_api/urls.py
from django.urls import path
from .views import get_po_data

urlpatterns = [
    path('api/po-data/', get_po_data),
]
