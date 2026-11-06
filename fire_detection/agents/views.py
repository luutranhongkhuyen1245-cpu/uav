import logging
import time
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, HttpResponseBadRequest, StreamingHttpResponse, JsonResponse
from django.utils import timezone
from django.core.mail import send_mail
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.views.decorators import gzip
from accounts.models import CustomUser
from projects.models import Cam, Zone, Alert
from .models import AgentProfile
from .forms import AgentCreationForm, AgentProfileForm
from .camera_utils import VideoCamera, gen, active_cameras, active_fire_states

logger = logging.getLogger(__name__)


@login_required
def add_agent(request):
    if request.user.user_type != CustomUser.USER_TYPE_SUPERVISOR:
        return HttpResponseForbidden("Access denied")
    
    if request.method == 'POST':
        user_form = AgentCreationForm(request.POST)
        profile_form = AgentProfileForm(request.POST)
        
        if user_form.is_valid() and profile_form.is_valid():
            # Create agent user as inactive
            agent_user = user_form.save()
            agent_user.is_active = False
            agent_user.save()
            
            # Save agent profile
            agent_profile = profile_form.save(commit=False)
            agent_profile.user = agent_user
            agent_profile.save()
            
            # Generate activation link
            uid = urlsafe_base64_encode(force_bytes(agent_user.pk))
            token = default_token_generator.make_token(agent_user)
            activate_url = request.build_absolute_uri(f"/accounts/activate/{uid}/{token}/")
            
            # Get generated password from form
            generated_password = user_form.generated_password
            
            # Send activation email
            subject = 'Your Fire Detection System Agent Account'
            message = f'''Hello {agent_user.get_full_name() or agent_user.email},

            Your agent account has been created for the Fire Detection System.

            Account Details:
            - Email: {agent_user.email}
            - Password: {generated_password}

            Please activate your account by clicking the link below:
            {activate_url}

            After activation, you can log in using the email and password provided above.

            Best regards,
            Fire Detection System Team'''
            
            # Debug: Print email configuration before sending
            print(f"\n=== Email Configuration Debug ===")
            print(f"EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
            print(f"EMAIL_HOST: {settings.EMAIL_HOST}")
            print(f"EMAIL_PORT: {settings.EMAIL_PORT}")
            print(f"EMAIL_USE_TLS: {settings.EMAIL_USE_TLS}")
            print(f"EMAIL_USE_SSL: {settings.EMAIL_USE_SSL}")
            print(f"EMAIL_HOST_USER: {settings.EMAIL_HOST_USER}")
            print(f"DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
            print(f"Recipient: {agent_user.email}")
            print(f"================================\n")
            
            try:
                # Use get_connection to ensure we're using the correct backend
                from django.core.mail import get_connection
                connection = get_connection()
                print(f"Using connection: {connection}")
                
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[agent_user.email],
                    fail_silently=False,
                    connection=connection,
                )
                messages.success(request, f'Tài khoản chuyên viên {agent_user.email} đã được tạo thành công! Email kích hoạt đã được gửi.')
            except Exception as e:
                # Log the full error for debugging
                import traceback
                error_details = traceback.format_exc()
                print(f"\n=== Email sending error ===")
                print(f"Error: {str(e)}")
                print(f"Full traceback:\n{error_details}")
                print(f"===========================\n")
                messages.error(request, f'Tài khoản {agent_user.email} đã được tạo nhưng gặp lỗi khi gửi email kích hoạt: {str(e)}.')
            
            return redirect('supervisor_dashboard')
    
    else:
        user_form = AgentCreationForm()
        profile_form = AgentProfileForm()
    
    return render(request, 'agents/add_agent.html', {
        'user_form': user_form,
        'profile_form': profile_form
    })

@login_required
def agent_list(request):
    # Kiểm tra quyền: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống.")
    
    # Récupérer tous les agents avec leurs profils
    agents = CustomUser.objects.filter(
        user_type=CustomUser.USER_TYPE_AGENT
    ).select_related('agentprofile')
    
    # Calculate statistics
    total_agents = agents.count()
    active_accounts = agents.filter(is_active=True).count()
    active_profiles = sum(1 for agent in agents if hasattr(agent, 'agentprofile') and agent.agentprofile and agent.agentprofile.is_active)
    inactive_count = total_agents - active_accounts
    
    context = {
        'agents': agents,
        'total_agents': total_agents,
        'active_accounts': active_accounts,
        'active_profiles': active_profiles,
        'inactive_count': inactive_count,
    }
    
    return render(request, 'agents/agent_list.html', context)

@login_required
def agent_detail(request, agent_id):
    """
    Hiển thị thông tin chi tiết của Người vận hành UAV (Agent) và các phân khu được phân công phụ trách.
    """
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Access denied")
        
    agent = get_object_or_404(CustomUser, id=agent_id, user_type=CustomUser.USER_TYPE_AGENT)
    assigned_zones = []
    if hasattr(agent, 'agentprofile'):
        assigned_zones = agent.agentprofile.assigned_zones.select_related('name_project').prefetch_related('cameras')
        
    return render(request, 'agents/agent_detail.html', {
        'agent': agent,
        'assigned_zones': assigned_zones,
    })

@login_required
def complete_profile(request):
    """
    Onboarding view for Agents who registered without an AgentProfile.
    Prompts the user to complete their profile (name, phone, address).
    """
    if request.user.user_type != CustomUser.USER_TYPE_AGENT:
        return redirect('/')

    # If the user already has a profile, go straight to dashboard
    if hasattr(request.user, 'agentprofile'):
        return redirect('agent_dashboard')

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        address = request.POST.get('address', '').strip()

        # Update User name if provided
        if first_name or last_name:
            request.user.first_name = first_name
            request.user.last_name = last_name
            request.user.save()

        # Create AgentProfile
        AgentProfile.objects.create(
            user=request.user,
            phone_number=phone_number,
            address=address,
            is_active=True
        )

        messages.success(request, 'Hồ sơ nhân viên đã được kích hoạt và cập nhật thành công!')
        return redirect('agent_dashboard')

    return render(request, 'agents/complete_profile.html')


@login_required
def stream_superviseur(request, zone_id):
    """
    Hiển thị luồng video trực tiếp của DUY NHẤT 1 UAV TRỰC CHIẾN (Bay chính) trong phân khu tuần tra.
    1 Người vận hành UAV chỉ điều khiển 1 UAV tại 1 thời điểm; các UAV khác là UAV dự phòng.
    Admin, Supervisor và Agent đều xem chung 1 luồng này để đảm bảo bức tranh chiến thuật đồng bộ.
    Cho phép cất cánh thay thế UAV dự phòng khi có sự cố.
    """
    if request.user.user_type not in [CustomUser.USER_TYPE_AGENT, CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Bạn không có quyền truy cập luồng camera.")

    try:
        zone = Zone.objects.select_related('name_project', 'name_project__supervisor').get(Zone_ID=zone_id)
    except Zone.DoesNotExist:
        logger.error(f"Vùng với ID {zone_id} không tồn tại.")
        return HttpResponseBadRequest("Không tìm thấy vùng tuần tra.")

    # Kiểm tra phân quyền cách ly dữ liệu theo Phân khu (Zone):
    if request.user.user_type == CustomUser.USER_TYPE_AGENT:
        if not zone.assigned_agents.filter(user=request.user).exists():
            return HttpResponseForbidden("Truy cập bị từ chối: Bạn chưa được phân công phụ trách phân khu này.")
    elif request.user.user_type == CustomUser.USER_TYPE_SUPERVISOR:
        if zone.name_project.supervisor and zone.name_project.supervisor != request.user:
            return HttpResponseForbidden("Truy cập bị từ chối: Vùng tuần tra này thuộc dự án của Điều phối viên khác.")
        elif zone.name_project.supervisor is None:
            zone.name_project.supervisor = request.user
            zone.name_project.save(update_fields=['supervisor'])

    active_camera = zone.active_camera
    standby_cameras = zone.standby_cameras

    # Quản lý phiên giám sát (MonitoringSession):
    from projects.models import MonitoringSession, SystemSetting
    active_session = MonitoringSession.objects.filter(
        zone=zone,
        status=MonitoringSession.STATUS_ACTIVE
    ).first()

    if not active_session:
        active_session = MonitoringSession.objects.create(
            project=zone.name_project,
            zone=zone,
            camera=active_camera,
            operator=request.user,
            status=MonitoringSession.STATUS_ACTIVE
        )
    elif active_camera and active_session.camera != active_camera:
        active_session.camera = active_camera
        active_session.save(update_fields=['camera'])

    ai_settings = SystemSetting.get_settings()

    return render(request, 'agents/stream_superviseur.html', {
        'active_camera': active_camera,
        'standby_cameras': standby_cameras,
        'cameras': [active_camera] if active_camera else [],
        'zone_id': zone_id,
        'zone': zone,
        'session': active_session,
        'ai_settings': ai_settings,
    })

@gzip.gzip_page
@login_required
def video_feed(request, cam_id):
    """
    Vue pour le flux vidéo en streaming depuis une caméra spécifique.
    Tối ưu tái sử dụng instance VideoCamera đang chạy để đồng bộ hóa phát hiện và tránh xung đột file MP4.
    """
    try:
        cam = get_object_or_404(Cam, cam_ID=cam_id)
        
        logger.info(f"[VIDEO_FEED] Yêu cầu luồng camera: {cam.name_cam} (ID: {cam_id})")

        # Xây dựng URL hoặc đường dẫn file MP4
        if hasattr(cam, 'is_full_rtsp_url') and cam.is_full_rtsp_url and cam.custom_url:
            rtsp_url = str(cam.custom_url).strip().strip('"').strip("'")
        elif cam.adresse_cam and cam.num_port:
            rest_path = getattr(cam, 'rest_de_path', '') or ''
            rtsp_url = f"rtsp://{cam.adresse_cam}:{cam.num_port}{rest_path}"
        else:
            logger.error(f"[VIDEO_FEED] Cấu hình camera ID {cam_id} không hợp lệ.")
            return HttpResponseBadRequest("Cấu hình camera không hợp lệ.")

        cam_name = cam.name_cam or f"Camera_{cam.cam_ID}"

        # Tái sử dụng VideoCamera đang chạy nếu có
        existing_cam = active_cameras.get(cam.cam_ID)
        if existing_cam and getattr(existing_cam, 'running', False) and hasattr(existing_cam, 'video') and existing_cam.video.isOpened():
            camera = existing_cam
        else:
            camera = VideoCamera(rtsp_url, cam_name, cam_id=cam.cam_ID)
        
        response = StreamingHttpResponse(
            gen(camera),
            content_type='multipart/x-mixed-replace; boundary=frame'
        )
        
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        response['X-Accel-Buffering'] = 'no'
        
        return response

    except Exception as e:
        logger.error(f'[VIDEO_FEED] Lỗi luồng camera ID={cam_id}: {e}', exc_info=True)
        return HttpResponseBadRequest(f"Lỗi: {e}")

@login_required
def check_camera_alert(request, cam_id):
    """
    API endpoint kiểm tra trạng thái cảnh báo cháy thời gian thực cho từng Camera UAV.
    Đồng bộ dữ liệu phát hiện trực tiếp từ RAM của VideoCamera và CSDL.
    """
    numeric_id = int(cam_id) if str(cam_id).isdigit() else cam_id

    # 1. Trạng thái phát hiện thời gian thực từ luồng video đang chạy (YOLO)
    cam_obj = active_cameras.get(numeric_id) or active_cameras.get(cam_id)
    is_fire = False
    alert_data = None

    if cam_obj:
        if getattr(cam_obj, 'is_fire_detected', False):
            is_fire = True
        active_info = getattr(cam_obj, 'get_active_alert_info', lambda: None)()
        if active_info:
            alert_data = active_info
            
    if not is_fire and ((time.time() - active_fire_states.get(numeric_id, 0) < 5) or (time.time() - active_fire_states.get(cam_id, 0) < 5)):
        is_fire = True

    # 2. Nếu chưa có thông tin alert trong RAM, truy vấn từ Alert mới nhất trong DB
    if not alert_data:
        recent_alert = Alert.objects.filter(
            camera_id=numeric_id,
            status=Alert.STATUS_NEW
        ).order_by('-detected_at').first()

        if recent_alert:
            is_fire = True
            alert_data = {
                'id': recent_alert.id,
                'label': recent_alert.class_label,
                'confidence': f"{recent_alert.confidence_percent}%",
                'time': timezone.localtime(recent_alert.detected_at).strftime("%H:%M:%S"),
                'video_time': f"{int(recent_alert.video_timestamp or 0)}s",
                'evidence_url': f"/media/{recent_alert.evidence_image}" if recent_alert.evidence_image else ""
            }

    return JsonResponse({
        'cam_id': numeric_id,
        'fire_detected': is_fire,
        'alert': alert_data
    })
