import datetime
from collections import defaultdict
from django.contrib.auth.models import User, Group
from django.db.models import Prefetch, Q, Func, F
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from automater.common_utility import get_standard_logger
from automater.backend_utilities import BackendAPI, validate_api
from automate.backend_utilities import get_formatted_data, copy_process_utility, check_strat_run
from automate.models import PendingProcess, Box, Region, Strategy, TickerPlant, GenericProcess, CalenderEvents, PROCESS_MAP, KillSwitch, Currency, Teams, RegionStrategyManage, UserWatchlistConfig, ExchangeRates
from automate.tasks import add_strategy_to_subteam
from automate.serializers import UserSerializer, GroupSerializer, PendingProcessSerializer, BoxSerializer, TeamsSerializer, CurrencySerializer, RegionSerializer, ProcessSerializer, KillSwitchSerializer, ExchangeRatesSerializer, UserWatchlistConfigSerializer, RegionStrategyManagerSerializer, StrategySerializer
from errormails.models import ErrorMail
from subteams.models import SubTeam

from redisHome.redis_data import get_jwt_token


logger = get_standard_logger(__name__, 'automate_backend.logs')


class UserViewSet(BackendAPI):
    """
    API endpoint that allows users to be viewed or edited.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer


class GroupViewSet(BackendAPI):
    """
    API endpoint that allows groups to be viewed or edited.
    """
    queryset = Group.objects.all()
    serializer_class = GroupSerializer


class BoxViewSet(BackendAPI):
    """
    API endpoint that allows boxes to be viewed or edited.
    """
    queryset = Box.objects.all()
    serializer_class = BoxSerializer


class TeamsViewSet(BackendAPI):
    """
    API endpoint that allows boxes to be viewed or edited.
    """
    queryset = Teams.objects.all()
    serializer_class = TeamsSerializer


class CurrencyViewSet(BackendAPI):
    """
    API endpoint that allows boxes to be viewed or edited.
    """
    queryset = Currency.objects.all()
    serializer_class = CurrencySerializer


class RegionViewSet(BackendAPI):
    """
    API endpoint that allows regions to be viewed or edited.
    """
    queryset = Region.objects.all()
    serializer_class = RegionSerializer


class RegionStrategyManagerViewSet(BackendAPI):
    """
    API endpoint that allows regions to be viewed or edited.
    """
    serializer_class = RegionStrategyManagerSerializer

    def get_queryset(self):
        return RegionStrategyManage.objects.filter(user__pk=self.request.user.id)


class PendingProcessViewSet(BackendAPI):
    """
    API endpoint that allow all process in pending state, before adding in actual model is added or edited
    """
    serializer_class = PendingProcessSerializer
    strategy_serializer = ProcessSerializer
    http_method_names = ModelViewSet.http_method_names

    def get_queryset(self):
        return PendingProcess.objects.filter(owner__pk=self.request.user.id)

    @validate_api()
    def create(self, request, *args, **kwargs):

        form_data = request.data.copy()
        request_user = User.objects.get(pk=request.user.id)
        if not request_user.is_staff:
            raise PermissionDenied('You do not have permission to add new Strategy.')
        form_data['owner'] = request.user.id
        serializer = self.serializer_class(data=form_data)
        if serializer.is_valid():
            serializer.save()
            return self.create_success_response(serializer.data)
        return self.create_error_response(form_errors=serializer.errors)

    @validate_api()
    def partial_update(self, request, pk=None):
        form_data = request.data.get('patch', {})
        if not (pk or form_data):
            raise Exception('Either PK is not provided or no fields to modify.')
        create_strategy = request.data.get("create_strategy", False)
        pending_object = PendingProcess.objects.get(id=pk)

        if pending_object.process:
            serializer = self.strategy_serializer(pending_object.process, data=form_data, partial=True)
        elif create_strategy:
            pending_serializer = PendingProcessSerializer(pending_object)
            data_dict = {**pending_serializer.data, **form_data, 'state': 'DORMANT'}
            serializer = ProcessSerializer(data=data_dict)
        else:
            serializer = self.serializer_class(pending_object, form_data, partial=True)
        if not serializer.is_valid():
            return self.create_error_response(form_errors=serializer.errors)

        serializer.save()
        pending_object = PendingProcess.objects.get(id=pk)
        if create_strategy:
            strategy = Strategy.objects.get(name=pending_object.name)
            pending_object.process = strategy
            pending_object.save()

        pending_serializer = PendingProcessSerializer(pending_object)
        return self.create_success_response(pending_serializer.data)

    @validate_api()
    def fetch_process_pending_actions(self, request):
        """
        View to list all Pending Process addition requests based on process type.
        """
        try:
            args = request.GET
            process_id = args['process_id']
            process_model = PROCESS_MAP[args["process_type"]]
            process = process_model.priv.filter(pk=process_id).select_related('killswitch', 'pnlinfo', 'pnllimits',
                                                                              "relationship").prefetch_related(
                "binrelease_set", "subteam_set", "unittestconfig_set", "strategy", "phlnamestrategymapping_set",
                Prefetch('errorobj', to_attr='errormails')).last()
            if not process:
                raise Exception('No process with given pk')
            data = {
                "process": process.name,
                "subteam": get_formatted_data(process, "subteam_set", msg_field='name', many_to_many=True),
                "killswitch": get_formatted_data(process, "killswitch"),
                "errormail": {"id": process.name if len(process.errormails) > 0 else None},
                "binrelease": get_formatted_data(process, "binrelease_set", msg_field="name", many_to_many=True),
                "unittest": get_formatted_data(process, "unittestconfig_set", many_to_many=True),
                "strat_userid_mapping": get_formatted_data(process, "strategy", many_to_many=True),
                "phl_mapping": get_formatted_data(process, "phlnamestrategymapping_set", many_to_many=True),
                "pnl_info": get_formatted_data(process, "pnlinfo"),
                "pnllimits": get_formatted_data(process, "pnllimits"),
            }
            return self.create_success_response(data)
        except Exception as e:
            data = {"error": str(e)}
            return self.create_error_response(error_message=str(e))

    @validate_api()
    @action(detail=True, methods=['POST'])
    def complete_pending_process(self, request, pk=None):
        """
        publish an existing process-- delete the pending process and Mark process active
        """
        pending_process = PendingProcess.objects.get(pk=pk)
        request_data = request.data
        mark_active = request_data.get('mark_active', False) == True
        process = pending_process.process
        if mark_active:
            if not process:
                raise Exception(f'No linked strategy exists for pending process - {pending_process.name}')
            process.state = 'ACTIVE'
            process.save()
        pending_process.delete()
        return self.create_success_response({'ok': True})

#
# class StrategyTableViewSet(BackendAPI):
#     serializer_class = ProcessSerializer
#
#     def get_queryset(self):
#         return Strategy.priv.all()
#
#     def list(self, request, *args, **kwargs):
#         queryset = self.get_queryset()
#         requested_fields = request.GET.get('fields', None)
#         requested_fields = requested_fields.split(',') if requested_fields else None
#         page = self.paginate_queryset(queryset)
#         if page is not None:
#             serializer = self.get_serializer(page, many=True, fields=requested_fields)
#             paged_data = self.paginator.add_page_info(serializer.data)
#             return self.create_success_response(paged_data)
#         serializer = self.get_serializer(queryset, many=True, fields=requested_fields)
#         return self.create_success_response(serializer.data)


class KillSwitchViewSet(BackendAPI):
    serializer_class = KillSwitchSerializer

    def get_queryset(self):
        return KillSwitch.objects.all().select_related('strategy')


class ProcessViewSet(BackendAPI):
    """
    API endpoint that allows strategies to be viewed or edited.
    """

    serializer_class = ProcessSerializer

    def get_queryset(self, edit=False):
        if not edit and SubTeam.objects.filter(name__icontains='recon').exists():
            user = User.objects.get(pk=self.request.user.id)
            return Strategy.priv.filter_by_recon(user)
        return Strategy.objects.all()

    @validate_api()
    def partial_update(self, request, pk=None):
        form_data = request.data
        strategy = self.get_queryset(edit=True).filter(pk=pk).last()
        if not strategy:
            return self.create_error_response(error_message='Not allowed to edit this strategy')
        allow_force_cpu_update = request.data.get('allow_force_cpu_update', False)
        logger.info(f'Process partial update requested for {strategy.name}, input params - {str(form_data)}, user- {request.user}')
        serializer = ProcessSerializer(strategy, data=form_data, partial=True)
        if not serializer.is_valid():
            return self.create_error_response(form_errors=serializer.errors)
        serializer.save(allow_force_cpu_update=allow_force_cpu_update)
        return self.create_success_response(serializer.data)

    @validate_api()
    @action(detail=True, methods=['POST'])
    def copy_process(self, request, pk=None):
        """
        Copy an existing process
        """
        orig_process = Strategy.objects.filter(pk=pk).last()
        request_data = request.data
        if not orig_process:
            return self.create_error_response(error_message={"message": f"Process with given PK {pk} doesn't exists"})
        new_name = request_data.get('new_name', None)
        new_box_id = request_data.get('new_box', None)
        new_box = Box.objects.filter(pk=new_box_id).last()
        copy_trading_session_flag = request_data.get('copy_trading_session_flag', False)
        copy_universal_error_flag = request_data.get('copy_universal_error_flag', False)
        copy_reports_flag = request_data.get('copy_reports_flag', False)

        if not (new_box_id and new_name and new_box):
            raise Exception("Name and new_box are required fields. and box with given name should exist.")

        request_user = User.objects.get(pk=request.user.id)
        status, data = copy_process_utility(orig_process, request_user, request_data=request_data)
        # Note- do not use orig_process after calling this function as it will be udpated to the new process created
        if status:
            return self.create_success_response(data)
        return self.create_error_response(form_errors=data)

    @validate_api()
    def api_post(self, request):
        slug_data = {"box": "name", "owner": "username", "currency": "symbol", "ERegion": "name", "team": "name"}
        form_data = request.data
        if self.user_type(request.user) != "subteam":
            raise Exception("This api is only allowed for subteams")
        serializer = self.serializer_class(data=form_data, slug_data=slug_data)
        if serializer.is_valid():
            serializer.save()
            if Strategy.current_subteam:
                add_strategy_to_subteam.delay(serializer.data['pk'], Strategy.current_subteam.name)
            return self.create_success_response(serializer.data)
        return self.create_error_response(form_errors=serializer.errors)

    @validate_api()
    def pnl(self, request):
        """
        Fetch all strategies for which we need to show pnl
        checks -
        """
        region_name = request.GET.get('region_name', '')
        strategy_names = request.GET.get('strategy_names', '')
        all_strategies = Strategy.objects.filter(state='ACTIVE').exclude(pnlinfo=None).prefetch_related(
            'box', 'ERegion', 'box__region', 'box__timezone', 'relationship', 'pnlinfo', 'currency', 'team',
            Prefetch(
            'errorobj',
            queryset=ErrorMail.objects.filter(error_type='crash'),
            to_attr='errormails')
        )
        if region_name:
            all_strategies = all_strategies.filter(ERegion__name=region_name)
        if strategy_names:
            all_strategies = all_strategies.filter(name__in=strategy_names.split(','))
        strategy_dict = check_strat_run(all_strategies)
        return self.create_success_response(data=strategy_dict)


class ExchangeRatesViewSet(BackendAPI):
    """ API endpoints for getting correct exchange correct rates """
    queryset = ExchangeRates.objects.all()
    serializer_class = ExchangeRatesSerializer

    @validate_api()
    def get_currency_rates(self, request, *args, **kwargs):
        request_date = request.GET.get('request_date', None)
        exchange_rates = self.queryset.filter(applied_date=request_date).last() if request_date else self.queryset.last()
        serializer = self.serializer_class(exchange_rates)
        return self.create_success_response(serializer.data)


class UserWatchlistConfigViewSet(BackendAPI):
    """ API endpoints for PNL page watchlist configs """
    serializer_class = UserWatchlistConfigSerializer

    def get_queryset(self):
        return UserWatchlistConfig.objects.filter(owner__pk=self.request.user.id)

    def create(self, request, *args, **kwargs):
        form_data = {**request.data.copy(), 'owner': request.user.id}
        serializer = self.serializer_class(data=form_data)
        if serializer.is_valid():
            serializer.save()
            return self.create_success_response(serializer.data)
        return self.create_error_response(form_errors=serializer.errors)

    @validate_api()
    def partial_update(self, request, pk=None):
        form_data = request.data
        user_watchlist_obj = self.get_queryset().get(pk=pk)
        serializer = self.serializer_class(user_watchlist_obj, data=form_data, partial=True)
        if not serializer.is_valid():
            return self.create_error_response(form_errors=serializer.errors)
        serializer.save()
        return self.create_success_response(serializer.data)


class QeUserRefreshTokenView(BackendAPI):  # CSRFExemptMixin

    permission_classes = []
    authentication_classes = []
    serializer_class = TokenRefreshSerializer

    def post(self, request, *args, **kwargs):
        refresh_token = request.POST.get('refresh')
        if not get_jwt_token(refresh_token):
            serializer = self.serializer_class(data=request.data)
            try:
                serializer.is_valid(raise_exception=True)
            except TokenError as e:
                return self.create_error_response(error_message=str(e), status_code=403)
            return self.create_success_response(serializer.validated_data)

        return self.create_error_response(error_message="Token is expired because user logged out", status_code=403)