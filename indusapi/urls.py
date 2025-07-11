# indus_api/urls.py
from django.urls import path
from .views import get_po_data
from . import views

urlpatterns = [
    path('api/po-data/', get_po_data),
    
    path('bulkscrape/', views.bulk_scrape, name='bulk_scrape'),
    
    #this for only api health checkup
    path('health/', views.health_check, name='health_check'),
]
