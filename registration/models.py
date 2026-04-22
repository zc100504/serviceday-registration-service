from django.db import models


class Registration(models.Model):
    employee_id = models.IntegerField()
    ngo_id = models.IntegerField()
    registered_at = models.DateTimeField(auto_now_add=True)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('employee_id', 'ngo_id')

    def __str__(self):
        return f"Employee {self.employee_id} - NGO {self.ngo_id}"