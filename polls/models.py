from django.db import models

# Create your models here.

from django.contrib.auth.models import User


TEAM_TYPE_CHOICES = (
    ('internal', 'internal'),
    ('external', 'external')
)


class Teams(models.Model):
    slack_id = models.CharField(max_length=20, null=True)
    secondary_slack_id = models.CharField(max_length=20, null=True)
    name = models.CharField(max_length=200, unique=True)
    lead = models.ManyToManyField(User, related_name='lead')
    users = models.ManyToManyField(User, through='TeamMembership')
    team_type = models.CharField(choices=TEAM_TYPE_CHOICES, max_length=100, default='internal')
    email = models.EmailField(max_length=70, blank=True, null=True, unique=False)
    api_hash = models.CharField(max_length=200, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    modified_date = models.DateTimeField(auto_now=True, null=True)

class TeamMembership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    team = models.ForeignKey(Teams, on_delete=models.CASCADE)
    date_joined = models.DateTimeField(auto_now_add=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    modified_date = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        index_together = [
            ['user', 'team']
        ]

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    primary_team = models.ForeignKey(Teams, on_delete=models.PROTECT, default=None, null=True)
    box_username = models.CharField(max_length=100, default=None, null=True, unique=True)
    is_internal = models.BooleanField(default=False)
    sound_choice = models.BooleanField(default=False)
    slack_id = models.CharField(max_length=100, null=True)
    asana_id = models.CharField(max_length=100, null=True)
    phone = models.CharField(max_length=15, default=None, null=True)
    extension_no = models.CharField(max_length=15, default=None, null=True)
    image_location = models.CharField(max_length=200, default=None, null=True)
    institution = models.CharField(max_length=200, default=None, null=True)
    dob = models.DateField(default=None, null=True)
    doj = models.DateField(default=None, null=True)
    emp_id = models.CharField(max_length=100, default=None, null=True)
    anniversary_date = models.DateField(default=None, null=True)
    region_toHide = models.CharField(max_length=1000, default=None, null=True)
    column_toHide = models.CharField(max_length=1000, default=None, null=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    is_qeTeamEnabled = models.BooleanField(default=False)
    modified_date = models.DateTimeField(auto_now=True, null=True)
    designation = models.CharField(max_length=100, null=True, default=None)
