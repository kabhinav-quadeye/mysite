from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.urls import resolve
from django.core import serializers
from .models import User, UserProfile, TeamMembership
from . import redis_data


def index(request):
    return HttpResponse("Hello, world. You're at the polls index.")


def user_list(request):
    users = UserProfile.objects.filter(user__is_active=True).select_related('user')
    context = {
        'users': users,
    }
    return render(request, 'user_list.html', context)


def users(request):
    users_on_holiday = redis_data.get_user_holiday_redis() or {}
    url_name = resolve(request.path_info).__dict__["url_name"]
    is_api = request.GET.get('is_api', False) == True

    if is_api:
        requested_users = request.GET.get('users', '').split(',')
        users = User.objects.filter(username__in=requested_users).prefetch_related(
            'teammembership_set', 'userprofile'
        )
        data = []
        for user in users:
            teams = user.teammembership_set.all().values_list('team__name', flat=True)
            data.append({
                'email': user.email,
                'teams': ', '.join(teams),
                'doj': user.userprofile.doj,
                'image_location': '/static/img/profile/default.jpg'
            })
        return JsonResponse({'status': True, 'users': data})

    if url_name == 'users':
        usps = UserProfile.objects.exclude(user__is_active=False).order_by('user__username')
    elif url_name == 'inactive_users':
        usps = UserProfile.objects.exclude(user__is_active=True).order_by('user__username')

    for up in usps:
        tms = TeamMembership.objects.filter(user=up.user)
        teams = []
        for tm in tms:
            teams.append(tm.team.name)
        up.teams = ', '.join(teams)

    context = {
        'usps': usps,
        'users_on_holiday': users_on_holiday,
 
        'internal':True
    }

    return render(request, 'users.html', context)
