from django.urls import path
from . import views

urlpatterns = [
    path('my/', views.my_registration),                        # GET   - view my registration
    path('register/<int:ngo_id>/', views.register_activity),   # POST  - register
    path('cancel/', views.cancel_registration),                 # DELETE - cancel
    path('switch/<int:ngo_id>/', views.switch_registration),   # PUT   - switch
]