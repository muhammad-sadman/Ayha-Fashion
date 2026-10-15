from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/store/", views.store_api, name="api-store"),
    path("api/promo/", views.promo_api, name="api-promo"),
    path("api/orders/", views.order_api, name="api-orders"),
]
