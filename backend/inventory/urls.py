from django.urls import path

from . import views

urlpatterns = [
    path("product/", views.ProductCreateView.as_view(), name="inventory-product-create"),
    path("products/", views.ProductListView.as_view(), name="inventory-product-list"),
]
