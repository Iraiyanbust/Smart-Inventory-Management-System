from django.urls import path

from . import views

urlpatterns = [
    path("upload/", views.ProcessingUploadView.as_view(), name="processing-upload"),
    path("verify-save/", views.VerifySaveView.as_view(), name="processing-verify-save"),
]