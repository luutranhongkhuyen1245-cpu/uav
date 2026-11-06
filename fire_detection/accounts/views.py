from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django import forms
from accounts.models import CustomUser
from projects.models import Project, Zone, Cam
from .forms import LoginForm, RegisterForm
from .decorators import role_required
import json

User = get_user_model()


@never_cache
@require_http_methods(['GET', 'POST'])
def login_view(request):
    # Nếu người dùng đã đăng nhập từ trước, tự động chuyển về đúng Dashboard
    if request.user.is_authenticated:
        return dashboard_redirect(request)

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        password = form.cleaned_data['password']
        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            return dashboard_redirect(request)
        else:
            # Kiểm tra trường hợp tài khoản đúng mật khẩu nhưng chưa kích hoạt hoặc bị vô hiệu hóa
            user_check = User.objects.filter(email=email).first()
            if user_check and user_check.check_password(password) and not user_check.is_active:
                messages.warning(request, 'Tài khoản của bạn đang ở trạng thái chờ Quản trị viên hệ thống phê duyệt hoặc đã bị tạm khóa. Vui lòng liên hệ Quản trị viên hệ thống để được kích hoạt.')
            else:
                messages.error(request, 'Email hoặc mật khẩu không chính xác.')
    return render(request, 'accounts/login.html', {'form': form})

@never_cache
@require_http_methods(['GET', 'POST'])
def register_view(request):
    if request.user.is_authenticated:
        return dashboard_redirect(request)

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        password = form.cleaned_data['password1']
        # Mặc định đăng ký là Người vận hành UAV, tài khoản cần được Quản trị viên hệ thống phê duyệt trước khi đăng nhập
        user = User.objects.create_user(
            email=email, 
            password=password, 
            user_type=User.USER_TYPE_AGENT, 
            is_active=False
        )

        messages.info(request, 'Đăng ký tài khoản thành công! Tài khoản của bạn đang ở trạng thái chờ Quản trị viên hệ thống phê duyệt trước khi có thể đăng nhập.')
        return redirect('login')
    return render(request, 'accounts/register.html', {'form': form})

@require_http_methods(['GET'])
def activate_view(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        user = None
    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        messages.success(request, 'Kích hoạt tài khoản thành công! Bạn có thể đăng nhập ngay.')
        return redirect('login')
    messages.error(request, 'Liên kết kích hoạt không hợp lệ hoặc đã hết hạn.')
    return redirect('register')

@never_cache
@csrf_exempt
@require_http_methods(['GET', 'POST'])
def logout_view(request):
    logout(request)
    messages.success(request, 'Bạn đã đăng xuất khỏi hệ thống thành công.')
    return redirect('login')
    return redirect('login')

@login_required
def dashboard_redirect(request):
    """
    Điều hướng thông minh về đúng Dashboard theo vai trò của người dùng.
    """
    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        return redirect('admin_dashboard')
    elif request.user.user_type == CustomUser.USER_TYPE_SUPERVISOR:
        return redirect('supervisor_dashboard')
    return redirect('agent_dashboard')


class ProjectForm(forms.ModelForm):
    supervisor = forms.ModelChoiceField(
        queryset=CustomUser.objects.filter(user_type=CustomUser.USER_TYPE_SUPERVISOR),
        required=False,
        empty_label="-- Chưa phân công Điều phối viên --",
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Điều phối viên giám sát phụ trách"
    )

    class Meta:
        model = Project
        fields = ['name', 'supervisor', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập tên dự án / chuyến bay...'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 1, 'placeholder': 'Mục tiêu giám sát hoặc mô tả...'}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        import django.utils.timezone
        if not getattr(instance, 'start_date', None):
            instance.start_date = django.utils.timezone.now().date()
        if commit:
            instance.save()
        return instance


@role_required(User.USER_TYPE_ADMIN)
def admin_dashboard(request):
    """Bảng điều khiển Quản trị viên hệ thống (Admin).
    Hỗ trợ hiển thị chức năng điều hành và khởi tạo trực tiếp dự án mới.
    """
    if not request.user.is_authenticated:
        return redirect('login')
    if getattr(request.user, 'user_type', None) != User.USER_TYPE_ADMIN:
        messages.error(request, 'Truy cập bị từ chối: Chỉ dành cho Quản trị viên hệ thống.')
        return redirect('login')

    if request.method == 'POST' and request.POST.get('action') == 'create':
        form = ProjectForm(request.POST)
        if form.is_valid():
            p = form.save()
            messages.success(request, f"Đã khởi tạo dự án '{p.name}' thành công. Điều phối viên giám sát phụ trách có thể tiến hành phân vùng và cấu hình UAV.")
            return redirect('admin_dashboard')
    else:
        form = ProjectForm()

    return render(request, 'accounts/dashboard_admin.html', {'form': form})

@require_http_methods(['GET'])
@role_required(User.USER_TYPE_SUPERVISOR)
def supervisor_dashboard(request):
    return render(request, 'accounts/dashboard_supervisor.html')

@require_http_methods(['GET', 'POST'])
@role_required(User.USER_TYPE_ADMIN)
def manage_users(request):
    # Actions: activate, deactivate, delete, update
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        action = request.POST.get('action')
        try:
            target_user = User.objects.get(pk=user_id)
            if action == 'activate':
                target_user.is_active = True
                target_user.save()
                messages.success(request, f"Tài khoản {target_user.email} đã được kích hoạt thành công.")
            elif action == 'deactivate':
                target_user.is_active = False
                target_user.save()
                messages.success(request, f"Tài khoản {target_user.email} đã được vô hiệu hóa.")
            elif action == 'delete':
                if target_user == request.user:
                    messages.error(request, "Bạn không thể tự xóa tài khoản của chính mình!")
                else:
                    user_email = target_user.email
                    from projects.models import Project
                    supervised_count = Project.objects.filter(supervisor=target_user).count()
                    target_user.delete()
                    if supervised_count > 0:
                        messages.info(request, f"Đã giải phóng {supervised_count} dự án do {user_email} từng phụ trách. Tất cả dự án, phân khu và camera UAV vẫn được bảo toàn nguyên vẹn.")
                    messages.success(request, f"Đã xóa tài khoản {user_email} thành công.")
            elif action == 'update':
                # Update user fields from form
                new_email = request.POST.get('edit_email')
                new_first_name = request.POST.get('edit_first_name')
                new_last_name = request.POST.get('edit_last_name')
                new_user_type = request.POST.get('edit_user_type')
                new_password = request.POST.get('new_password', '').strip()
                if new_email:
                    target_user.email = new_email
                if new_first_name is not None:
                    target_user.first_name = new_first_name.strip()
                if new_last_name is not None:
                    target_user.last_name = new_last_name.strip()
                if new_user_type:
                    old_user_type = target_user.user_type
                    if old_user_type == User.USER_TYPE_SUPERVISOR and new_user_type != User.USER_TYPE_SUPERVISOR:
                        # Hạ quyền từ Điều phối viên giám sát sang vai trò khác: giải phóng các dự án phụ trách
                        from projects.models import Project
                        released_count = Project.objects.filter(supervisor=target_user).update(supervisor=None)
                        if released_count > 0:
                            messages.info(request, f"Đã giải phóng {released_count} dự án khỏi tài khoản {target_user.email}. Các dự án này hiện ở trạng thái 'Chưa phân công' và sẵn sàng để phân công Điều phối viên giám sát mới.")
                    
                    if new_user_type == User.USER_TYPE_AGENT:
                        from agents.models import AgentProfile
                        AgentProfile.objects.get_or_create(user=target_user)

                    target_user.user_type = new_user_type
                if new_password:
                    target_user.set_password(new_password)
                target_user.save()
                messages.success(request, f"Đã cập nhật thông tin tài khoản {target_user.email} thành công.")
        except User.DoesNotExist:
            messages.error(request, "Không tìm thấy người dùng.")

    # Tri et recherche
    sort = request.GET.get('sort', 'email')
    search = request.GET.get('search', '')
    users = User.objects.all()
    if search:
        users = users.filter(
            Q(email__icontains=search) | 
            Q(user_type__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )
    users = users.order_by(sort)

    # Statistics
    all_users = User.objects.all()
    total_users = all_users.count()
    active_users = all_users.filter(is_active=True).count()
    inactive_users = all_users.filter(is_active=False).count()
    admin_count = all_users.filter(user_type=User.USER_TYPE_ADMIN).count()
    supervisor_count = all_users.filter(user_type=User.USER_TYPE_SUPERVISOR).count()
    agent_count = all_users.filter(user_type=User.USER_TYPE_AGENT).count()

    # Edit form: if ?edit=<user_id> in GET, show edit form for that user
    edit_user = None
    if 'edit' in request.GET:
        try:
            edit_user = User.objects.get(pk=request.GET['edit'])
        except User.DoesNotExist:
            edit_user = None

    return render(request, 'accounts/manage_users.html', {
        'users': users,
        'sort': sort,
        'search': search,
        'edit_user': edit_user,
        'user_type_choices': User.USER_TYPE_CHOICES,
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'admin_count': admin_count,
        'supervisor_count': supervisor_count,
        'agent_count': agent_count,
    })


@require_http_methods(['GET', 'POST'])
@role_required(User.USER_TYPE_ADMIN)
def manage_projects(request):
    # Actions: create, update, delete (Admin chỉ quản lý cấu hình dự án, không vận hành ca bay)
    if request.method == 'POST':
        action = request.POST.get('action')
        project_id = request.POST.get('project_id')
        if action == 'create':
            form = ProjectForm(request.POST)
            if form.is_valid():
                p = form.save()
                messages.success(request, f"Đã khởi tạo dự án '{p.name}' thành công. Điều phối viên giám sát phụ trách có thể tiến hành phân vùng và cấu hình UAV.")
                return redirect('manage_projects')
        elif project_id:
            try:
                project = Project.objects.get(pk=project_id)
                if action == 'delete':
                    project.delete()
                    messages.success(request, "Đã xóa dự án thành công.")
                elif action == 'update':
                    form = ProjectForm(request.POST, instance=project)
                    if form.is_valid():
                        form.save()
                        messages.success(request, "Đã cập nhật dự án thành công.")
                        return redirect('manage_projects')
            except Project.DoesNotExist:
                messages.error(request, "Không tìm thấy dự án.")

    # Recherche et tri
    sort = request.GET.get('sort', 'created_at')
    search = request.GET.get('search', '')
    projects = Project.objects.all().prefetch_related('zones', 'zones__cameras', 'supervisor')
    if search:
        projects = projects.filter(name__icontains=search)
    projects = projects.order_by(sort)

    # Statistics
    all_projects = Project.objects.all()
    total_projects = all_projects.count()
    live_projects = all_projects.filter(status__in=['in_progress', 'active']).count()
    ready_projects = all_projects.filter(status='planned').count()
    active_projects = live_projects
    inactive_projects = total_projects - live_projects

    # Edit form: if ?edit=<project_id> in GET, show edit form for that project
    edit_project = None
    if 'edit' in request.GET:
        try:
            edit_project = Project.objects.get(pk=request.GET['edit'])
        except Project.DoesNotExist:
            edit_project = None

    # Formulaire de création ou d'édition
    if edit_project:
        form = ProjectForm(instance=edit_project)
    else:
        form = ProjectForm()

    return render(request, 'accounts/manage_projects.html', {
        'projects': projects,
        'sort': sort,
        'search': search,
        'edit_project': edit_project,
        'form': form,
        'total_projects': total_projects,
        'active_projects': active_projects,
        'inactive_projects': inactive_projects,
        'live_projects': live_projects,
        'ready_projects': ready_projects,
    })

@require_http_methods(['GET'])
@role_required(CustomUser.USER_TYPE_AGENT)
def agent_dashboard(request):
    if not hasattr(request.user, 'agentprofile'):
        return redirect('agents:complete_profile')

    agent_profile = request.user.agentprofile

    # Lọc các phân khu, dự án và camera mà Agent được phân công trực tiếp
    zones = Zone.objects.filter(assigned_agents=agent_profile).select_related('name_project')
    projects = Project.objects.filter(zones__in=zones).distinct()
    cameras = Cam.objects.filter(name_zone__in=zones)

    # Totaux
    total_projects = projects.count()
    total_zones = zones.count()
    total_cameras = cameras.count()

    # Construction JSON hiérarchique pour la carte
    projects_json = []

    for project in projects:
        project_zones = zones.filter(name_project=project)

        zone_list = []
        for zone in project_zones:
            zone_cameras = cameras.filter(name_zone=zone)

            zone_list.append({
                "id": zone.Zone_ID,
                "name": zone.name_zone,
                "description": zone.description_zone,
                "coords": zone.coords_polys if zone.coords_polys else [],
                "camera_count": zone_cameras.count(),
            })

        projects_json.append({
            "id": project.id,
            "name": project.name,
            "zone_count": project_zones.count(),
            "zones": zone_list,
        })

    return render(request, 'accounts/dashboard_agent.html', {
        "projects": projects,
        "zones": zones,
        "cameras": cameras,
        "total_projects": total_projects,
        "total_zones": total_zones,
        "total_cameras": total_cameras,

        # IMPORTANT
        "projects_json": json.dumps(projects_json, ensure_ascii=False),
    })
