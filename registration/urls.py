from django.urls import path
from . import views

urlpatterns = [
    path('', views.registrations_by_date), 
    path('my/', views.my_registration),                        # GET   - view my registration
    path('register/<int:ngo_id>/', views.register_activity),   # POST  - register
    path('cancel/', views.cancel_registration),                 # DELETE - cancel
    path('switch/<int:ngo_id>/', views.switch_registration),
    path('participants/<int:ngo_id>/', views.participants_list),      # GET   - view participants
    path('counts/', views.registration_counts),  # ← add this
    path('emails/', views.registration_emails),  # ← add this
    path('benchmark/<int:ngo_id>/', views.cache_benchmark),

]