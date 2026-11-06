from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from .models import Project, Zone, Cam, Alert, AlertReview, SystemSetting, MonitoringSession
from .forms import ProjectCreationForm
from accounts.models import CustomUser
from agents.models import AgentProfile
import json

@login_required
def create_project(request):
    # Kiểm tra quyền: Chỉ dành cho Điều phối viên giám sát
    if request.user.user_type != CustomUser.USER_TYPE_SUPERVISOR:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát.")
    
    if request.method == 'POST':
        form = ProjectCreationForm(request.POST, supervisor=request.user)
        if form.is_valid():
            try:
                project = form.save()
                messages.success(request, f'Dự án "{project.name}" đã được tạo thành công! Hãy tiếp tục định nghĩa các vùng tuần tra.')
                return redirect('projects:add_zone', project_id=project.id)
            except Exception as e:  
                messages.error(request, f'Có lỗi xảy ra khi tạo dự án: {str(e)}')
    else:
        form = ProjectCreationForm(supervisor=request.user)
    
    return render(request, 'projects/create_project.html', {'form': form})


@login_required
def add_zone(request, project_id):
    """
    View to add a zone (polygon) to a project.
    Hỗ trợ cả Chỉ huy bay (Supervisor) và Quản trị viên (Admin).
    Supervisor có thể phân vùng cho dự án của mình hoặc dự án do Admin tạo.
    """
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống.")
    
    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        projet_instance = get_object_or_404(Project, id=project_id)
    else:
        projet_instance = Project.objects.filter(
            Q(id=project_id) & (Q(supervisor=request.user) | Q(supervisor__isnull=True))
        ).first()
        if not projet_instance:
            projet_instance = get_object_or_404(Project, id=project_id)
        if projet_instance.supervisor is None:
            projet_instance.supervisor = request.user
            projet_instance.save(update_fields=['supervisor'])
            
    zones = Zone.objects.filter(name_project=projet_instance)
    
    # Convert JSON coordinates to JSON strings for the template
    zones_data = []
    for zone in zones:
        zones_data.append({
            'zone': zone,
            'coords_json': json.dumps(zone.coords_polys) if zone.coords_polys else 'null'
        })

    if request.method == 'POST':
        name_zone = request.POST.get('name_zone', '').strip()
        description_zone = request.POST.get('description', '').strip()
        multi_polygone = request.POST.get('coords_polys', '').strip()
        ajoutez_un_polygone = request.POST.get('ajoutez_un_polygone')
        
        # Nếu người dùng bấm "Hoàn tất: Cấu hình Camera UAV" khi đã có ít nhất 1 phân khu trước đó
        if (not name_zone or not multi_polygone) and not ajoutez_un_polygone and zones.exists():
            messages.info(request, f'Đã hoàn tất thiết lập {zones.count()} phân khu cho dự án "{projet_instance.name}". Tiếp tục cấu hình Camera UAV.')
            return redirect('projects:add_cam', name_zone=zones.first().Zone_ID)

        if not name_zone or not multi_polygone:
            messages.error(request, 'Vui lòng nhập tên phân khu và dùng công cụ đa giác vẽ ranh giới trên bản đồ.')
            zones_data = []
            for zone in zones:
                zones_data.append({
                    'zone': zone,
                    'coords_json': json.dumps(zone.coords_polys) if zone.coords_polys else 'null'
                })
            return render(
                request,
                'projects/add_zone.html',
                {
                    'votre_projet': projet_instance.name,
                    'project': projet_instance,
                    'project_id': projet_instance.id,
                    'zones': zones,
                    'zones_data': zones_data
                }
            )
        try:
            # Convert JSON text to Python dictionary
            coords_data = json.loads(multi_polygone)

            donnees_zone = Zone(
                name_zone=name_zone,
                description_zone=description_zone,
                coords_polys=coords_data,
                name_project=projet_instance
            )
            donnees_zone.save()

            zones = Zone.objects.filter(name_project=projet_instance)
            
            # Convert JSON coordinates to JSON strings for the template
            zones_data = []
            for zone in zones:
                zones_data.append({
                    'zone': zone,
                    'coords_json': json.dumps(zone.coords_polys) if zone.coords_polys else 'null'
                })

            if ajoutez_un_polygone:
                # User wants to add another polygon
                messages.success(request, f'Đã thêm phân khu "{name_zone}" thành công! Bạn có thể tiếp tục vẽ phân khu tiếp theo.')
                return render(
                    request,
                    'projects/add_zone.html',
                    {
                        'votre_projet': projet_instance.name,
                        'project': projet_instance,
                        'project_id': projet_instance.id,
                        'zones': zones,
                        'zones_data': zones_data
                    }
                )
            else:
                # Move to next step (add cameras)
                messages.success(request, f'Đã thiết lập thành công {zones.count()} phân khu tuần tra! Tiếp tục cấu hình Camera UAV.')
                return redirect('projects:add_cam', name_zone=zones.first().Zone_ID)

        except json.JSONDecodeError:
            messages.error(request, 'Lỗi: Định dạng tọa độ ranh giới không hợp lệ.')
        except Exception as e:
            messages.error(request, f'Có lỗi xảy ra khi tạo phân khu tuần tra: {str(e)}')

    # Convert JSON coordinates to JSON strings for the template
    zones_data = []
    for zone in zones:
        zones_data.append({
            'zone': zone,
            'coords_json': json.dumps(zone.coords_polys) if zone.coords_polys else 'null'
        })
    
    return render(
        request,
        'projects/add_zone.html',
        {
            'votre_projet': projet_instance.name,
            'project': projet_instance,
            'project_id': projet_instance.id,
            'zones': zones,
            'zones_data': zones_data
        }
    )

@login_required
def add_cam(request, name_zone):
    """
    Thêm Camera UAV vào một vùng tuần tra cụ thể hoặc chọn bất kỳ phân khu nào trong dự án.
    Hỗ trợ tìm kiếm theo ID vùng hoặc Tên vùng an toàn cho Chỉ huy bay.
    """
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống.")
    
    # Tìm kiếm theo Zone_ID nếu là số, hoặc theo Tên vùng
    if str(name_zone).isdigit():
        zone_instance = get_object_or_404(Zone, Zone_ID=int(name_zone))
    else:
        zone_instance = Zone.objects.filter(name_zone=name_zone).first()
        if not zone_instance:
            zone_instance = get_object_or_404(Zone, name_zone=name_zone)
    
    if request.user.user_type == CustomUser.USER_TYPE_SUPERVISOR and zone_instance.name_project.supervisor is None:
        zone_instance.name_project.supervisor = request.user
        zone_instance.name_project.save(update_fields=['supervisor'])
    
    project = zone_instance.name_project
    zones = Zone.objects.filter(name_project=project)
    
    # Lấy danh sách tất cả camera UAV đã cấu hình trong toàn bộ dự án
    all_project_cams = Cam.objects.filter(name_zone__name_project=project).select_related('name_zone')
    
    # Convert JSON coordinates to JSON strings for the template
    zones_data = []
    for zone in zones:
        zones_data.append({
            'zone': zone,
            'coords_json': json.dumps(zone.coords_polys) if zone.coords_polys else 'null'
        })

    if request.method == 'POST':
        # Phân khu được chọn từ dropdown
        target_zone_id = request.POST.get('target_zone_id')
        current_zone = zone_instance
        if target_zone_id:
            found_zone = zones.filter(Zone_ID=target_zone_id).first()
            if found_zone:
                current_zone = found_zone

        name_cam = request.POST.get('name_cam', '').strip()
        adresse_cam = request.POST.get('adresse_cam', '').strip() or None
        num_port = request.POST.get('num_port', '').strip() or None
        rest_de_path = request.POST.get('rest_de_path', '').strip() or None
        custom_url = request.POST.get('custom_url', '').strip() or None
        stream_type = request.POST.get('streamType', 'fullRtspUrl')
        description_cam = request.POST.get('description_cam', '').strip()
        ajoutez_un_cam = request.POST.get('ajoutez_un_cam')

        # Nếu người dùng bấm "Hoàn tất cấu hình" mà không nhập thêm camera mới nhưng dự án đã có ít nhất 1 camera UAV:
        if not name_cam and not ajoutez_un_cam and all_project_cams.exists():
            messages.info(request, f'Đã hoàn tất cấu hình {all_project_cams.count()} Camera UAV cho dự án "{project.name}".')
            return redirect('projects:project_detail', project_id=project.id)

        if not name_cam:
            messages.error(request, 'Vui lòng nhập Tên Camera UAV / Mã thiết bị bay.')
            return render(
                request,
                'projects/add_cam.html',
                {
                    'project_name': project.name,
                    'zone_name': current_zone.name_zone,
                    'zone_instance': current_zone,
                    'zones': zones,
                    'all_project_cams': all_project_cams,
                    'zones_data': zones_data,
                }
            )

        try:
            # Quyết định kiểu luồng
            if stream_type == 'fullRtspUrl' or custom_url:
                is_full_rtsp_url = True
                if custom_url:
                    custom_url = custom_url.strip('"').strip("'")
            else:
                is_full_rtsp_url = False

            if num_port:
                try:
                    num_port = int(num_port)
                except ValueError:
                    raise ValueError('Số hiệu cổng mạng (Port) phải là số nguyên.')
            else:
                num_port = None

            is_primary_req = request.POST.get('is_primary')
            # Nếu phân khu chưa có camera nào thì luôn là True, nếu có rồi thì theo lựa chọn của người dùng
            has_cams_in_zone = Cam.objects.filter(name_zone=current_zone).exists()
            is_primary_val = (is_primary_req == 'true') or (not has_cams_in_zone)

            donnees_cam = Cam(
                name_cam=name_cam,
                adresse_cam=adresse_cam,
                num_port=num_port,
                rest_de_path=rest_de_path,
                custom_url=custom_url,
                is_full_rtsp_url=is_full_rtsp_url,
                is_primary=is_primary_val,
                description_cam=description_cam,
                coords_cam=None,  # UAV di động trên không, không cần ghim cố định
                name_zone=current_zone
            )
            # Call full_clean() to execute the model's clean() method
            try:
                donnees_cam.full_clean()
            except ValidationError as e:
                error_messages = []
                if hasattr(e, 'message_dict'):
                    for field, errors in e.message_dict.items():
                        error_messages.extend(errors)
                else:
                    error_messages.append(str(e))
                messages.error(request, 'Lỗi thông số kết nối: ' + ' '.join(error_messages))
                return render(
                    request,
                    'projects/add_cam.html',
                    {
                        'project_name': project.name,
                        'zone_name': current_zone.name_zone,
                        'zone_instance': current_zone,
                        'zones': zones,
                        'all_project_cams': all_project_cams,
                        'zones_data': zones_data,
                    }
                )

            donnees_cam.save()

            if ajoutez_un_cam:
                messages.success(request, f'Đã thêm Camera UAV "{name_cam}" cho phân khu "{current_zone.name_zone}" thành công! Bạn có thể chọn phân khu khác để tiếp tục thêm UAV.')
                return redirect('projects:add_cam', name_zone=current_zone.Zone_ID)
            else:
                messages.success(request, f'Đã hoàn tất cấu hình Camera UAV! Dự án tuần tra "{project.name}" đã sẵn sàng.')
                return redirect('projects:project_detail', project_id=project.id)

        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Có lỗi xảy ra khi tạo camera UAV: {str(e)}')

    return render(
        request,
        'projects/add_cam.html',
        {
            'project_name': project.name,
            'zone_name': zone_instance.name_zone,
            'zone_instance': zone_instance,
            'zones': zones,
            'all_project_cams': all_project_cams,
            'zones_data': zones_data,
        }
    )

@login_required
def project_list(request):
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống.")
    
    # Supervisor thấy dự án của mình VÀ các dự án do Admin tạo trong hệ thống
    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        projects = Project.objects.all().prefetch_related('zones', 'zones__assigned_agents', 'zones__assigned_agents__user')
    else:
        projects = Project.objects.filter(
            Q(supervisor=request.user) | Q(supervisor__isnull=True)
        ).prefetch_related('zones', 'zones__assigned_agents', 'zones__assigned_agents__user')
    
    available_agents = AgentProfile.objects.filter(is_active=True).select_related('user')
    
    return render(request, 'projects/project_list.html', {
        'projects': projects,
        'available_agents': available_agents,
    })

@login_required
def delete_project(request, project_id):
    """Delete a project and all its related zones and cameras."""
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối.")

    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        project = get_object_or_404(Project, id=project_id)
    else:
        project = get_object_or_404(Project, id=project_id)
        if project.supervisor and project.supervisor != request.user:
            return HttpResponseForbidden("Bạn không có quyền xóa dự án của Điều phối viên khác.")

    if request.method == 'POST':
        project_name = project.name
        project.delete()
        messages.success(request, f'Dự án tuần tra "{project_name}" đã được xóa thành công.')
    
    return redirect('projects:project_list')

@login_required
def toggle_patrol_status(request, project_id):
    """
    Chỉ huy bay (Supervisor) bật / tạm dừng ca bay tuần tra Live cho dự án.
    Quản trị viên (Admin) chỉ xem tiến độ, không trực tiếp vận hành ca bay tuần tra thực địa.
    """
    if request.user.user_type != CustomUser.USER_TYPE_SUPERVISOR and not request.user.is_superuser:
        messages.error(request, "Chỉ Điều phối viên giám sát phụ trách mới có quyền điều hành ca bay tuần tra.")
        return HttpResponseForbidden("Chỉ Điều phối viên giám sát phụ trách mới có quyền điều hành ca bay tuần tra.")

    project = get_object_or_404(Project, id=project_id)

    # Quyền sở hữu của Điều phối viên
    if request.user.user_type == CustomUser.USER_TYPE_SUPERVISOR:
        if project.supervisor and project.supervisor != request.user:
            messages.error(request, "Bạn không có quyền điều hành dự án của Điều phối viên khác.")
            return redirect('projects:project_list')
        if not project.supervisor:
            project.supervisor = request.user
            project.save(update_fields=['supervisor'])

    if request.method == 'POST':
        # Nếu đang tuần tra Live -> Chuyển về tạm dừng (Sẵn sàng / planned)
        if project.status in ['in_progress', 'active']:
            project.status = 'planned'
            project.save(update_fields=['status'])
            messages.info(request, f'Đã tạm dừng ca bay tuần tra của dự án "{project.name}". Trạng thái chuyển về Sẵn sàng bay.')
        else:
            # Kiểm tra xem dự án đã đủ điều kiện bay chưa (đã có phân khu & camera UAV chưa)
            status_info = project.get_progress_status()
            if status_info['code'] == 'no_zones':
                messages.warning(request, f'Chưa thể bắt đầu tuần tra: Dự án "{project.name}" chưa có phân khu nào được vẽ. Vui lòng vẽ ranh giới trước.')
                return redirect('projects:add_zone', project_id=project.id)
            elif status_info['code'] == 'no_cams':
                messages.warning(request, f'Chưa thể bắt đầu tuần tra: Dự án "{project.name}" chưa gắn Camera UAV nào. Vui lòng cấu hình Camera UAV.')
                first_zone = project.first_zone
                return redirect('projects:add_cam', name_zone=first_zone.Zone_ID)

            project.status = 'in_progress'
            project.save(update_fields=['status'])
            messages.success(request, f'Đã kích hoạt ca bay tuần tra trực tiếp cho dự án "{project.name}". UAV đang thực hiện nhiệm vụ giám sát!')

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'projects:project_list'
    return redirect(next_url)

@login_required
def project_detail(request, project_id):
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống.")
    
    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        project = get_object_or_404(Project, id=project_id)
    else:
        project = Project.objects.filter(
            Q(id=project_id) & (Q(supervisor=request.user) | Q(supervisor__isnull=True))
        ).first()
        if not project:
            project = get_object_or_404(Project, id=project_id)
        if project.supervisor is None:
            project.supervisor = request.user
            project.save(update_fields=['supervisor'])
    
    # Get all project zones with their cameras and assigned agents
    zones = Zone.objects.filter(name_project=project).prefetch_related('cameras', 'assigned_agents', 'assigned_agents__user')
    
    # Calculate total number of cameras
    total_cameras = sum(zone.cameras.count() for zone in zones)
    
    # Convert JSON coordinates to JSON strings for the template
    zones_data = []
    for zone in zones:
        cameras_data = []
        for cam in zone.cameras.all():
            cameras_data.append({
                'cam': cam,
                'coords_json': json.dumps(cam.coords_cam) if cam.coords_cam else 'null'
            })
        zones_data.append({
            'zone': zone,
            'coords_json': json.dumps(zone.coords_polys) if zone.coords_polys else 'null',
            'cameras_data': cameras_data
        })
    
    # Get all available active UAV operators for assignment
    available_agents = AgentProfile.objects.filter(is_active=True).select_related('user')
    assigned_agent_ids = set(project.assigned_agents.values_list('id', flat=True))
    
    return render(request, 'projects/project_detail.html', {
        'project': project,
        'zones_data': zones_data,
        'zones': zones,
        'total_cameras': total_cameras,
        'available_agents': available_agents,
        'assigned_agent_ids': assigned_agent_ids,
    })

@login_required
def assign_zone_agents(request, zone_id):
    """
    Phân công hoặc cập nhật danh sách Chuyên viên vận hành UAV cho từng Phân khu (Zone) cụ thể.
    """
    from agents.models import AgentProfile

    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống.")

    zone = get_object_or_404(Zone.objects.select_related('name_project'), Zone_ID=zone_id)
    project = zone.name_project

    if request.user.user_type == CustomUser.USER_TYPE_SUPERVISOR:
        if project.supervisor and project.supervisor != request.user:
            return HttpResponseForbidden("Bạn không có quyền phân công cho dự án của Điều phối viên khác.")
        if project.supervisor is None:
            project.supervisor = request.user
            project.save(update_fields=['supervisor'])

    if request.method == 'POST':
        selected_agent_ids = request.POST.getlist('agent_ids')
        agents_to_assign = AgentProfile.objects.filter(id__in=selected_agent_ids, is_active=True)
        zone.assigned_agents.set(agents_to_assign)

        assigned_names = [a.user.email for a in agents_to_assign]
        if assigned_names:
            messages.success(request, f'Đã phân công {len(assigned_names)} Người vận hành UAV phụ trách phân khu "{zone.name_zone}" ({project.name}).')
        else:
            messages.info(request, f'Đã hủy phân công Người vận hành UAV khỏi phân khu "{zone.name_zone}".')

        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
        if next_url:
            return redirect(next_url)
    return redirect('projects:project_detail', project_id=project.id)

@login_required
def switch_active_camera(request, zone_id, cam_id):
    """
    Chuyển đổi UAV Trực chiến (Bay chính) trong Phân khu tuần tra.
    Người có quyền thực hiện:
    - Quản trị viên hệ thống (Admin): Toàn quyền
    - Điều phối viên giám sát (Supervisor): Phụ trách dự án này
    - Người vận hành UAV (Agent): Phụ trách phân khu này
    """
    zone = get_object_or_404(Zone.objects.select_related('name_project', 'name_project__supervisor'), Zone_ID=zone_id)
    target_cam = get_object_or_404(Cam, cam_ID=cam_id, name_zone=zone)

    # Kiểm tra phân quyền: Chỉ Người vận hành UAV (Agent) phụ trách phân khu mới được phép chọn cất cánh
    has_permission = False
    if request.user.user_type == CustomUser.USER_TYPE_AGENT:
        if zone.assigned_agents.filter(user=request.user).exists():
            has_permission = True
    elif request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        has_permission = True

    if not has_permission:
        err_msg = 'Chỉ Người vận hành UAV (Agent) phụ trách phân khu mới có quyền chọn cất cánh và chuyển đổi UAV.'
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'status': 'error', 'message': err_msg}, status=403)
        messages.error(request, err_msg)
        return HttpResponseForbidden(err_msg)

    # Đặt target_cam làm primary
    target_cam.is_primary = True
    target_cam.save()

    # Cập nhật MonitoringSession đang hoạt động (nếu có)
    from projects.models import MonitoringSession
    active_session = MonitoringSession.objects.filter(
        zone=zone,
        status=MonitoringSession.STATUS_ACTIVE
    ).first()
    if active_session:
        active_session.camera = target_cam
        active_session.save(update_fields=['camera'])

    msg = f'Đã chuyển sang UAV "{target_cam.name_cam}" làm UAV Trực chiến (Bay chính) cho phân khu "{zone.name_zone}".'
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json' or request.GET.get('format') == 'json':
        return JsonResponse({
            'status': 'success',
            'message': msg,
            'active_cam_id': target_cam.cam_ID,
            'active_cam_name': target_cam.name_cam,
            'stream_url': f"/agents/video_feed/{target_cam.cam_ID}/"
        })

    messages.success(request, msg)
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if next_url:
        return redirect(next_url)
    return redirect('agents:stream_cam', zone_id=zone.Zone_ID)

@login_required
def assign_agents(request, project_id):
    """
    Phân công nhanh Người vận hành UAV cho toàn bộ các phân khu của Dự án tuần tra.
    """
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống.")
        
    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        project = get_object_or_404(Project, id=project_id)
    else:
        project = Project.objects.filter(
            Q(id=project_id) & (Q(supervisor=request.user) | Q(supervisor__isnull=True))
        ).first()
        if not project:
            project = get_object_or_404(Project, id=project_id)
        if project.supervisor is None:
            project.supervisor = request.user
            project.save(update_fields=['supervisor'])
        
    if request.method == 'POST':
        selected_agent_ids = request.POST.getlist('agent_ids')
        agents_to_assign = AgentProfile.objects.filter(id__in=selected_agent_ids, is_active=True)
        # Gán cho toàn bộ các phân khu của dự án
        for z in project.zones.all():
            z.assigned_agents.set(agents_to_assign)
        
        assigned_names = [a.user.email for a in agents_to_assign]
        if assigned_names:
            messages.success(request, f'Đã phân công {len(assigned_names)} Người vận hành UAV cho tất cả phân khu của dự án "{project.name}".')
        else:
            for z in project.zones.all():
                z.assigned_agents.clear()
            messages.info(request, f'Đã hủy phân công toàn bộ Người vận hành UAV khỏi dự án "{project.name}".')
            
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
        if next_url:
            return redirect(next_url)
    return redirect('projects:project_detail', project_id=project.id)

@login_required
def update_project(request, project_id):
    """
    Cập nhật thông tin chi tiết dự án (Tên, Mục tiêu / Mô tả, Ngày bắt đầu, Trạng thái tuần tra).
    Cho phép Supervisor và Admin chỉnh sửa trực tiếp.
    """
    if request.user.user_type not in [CustomUser.USER_TYPE_SUPERVISOR, CustomUser.USER_TYPE_ADMIN]:
        return HttpResponseForbidden("Truy cập bị từ chối: Yêu cầu quyền Điều phối viên giám sát hoặc Quản trị viên hệ thống.")
    
    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        project = get_object_or_404(Project, id=project_id)
    else:
        project = get_object_or_404(Project, id=project_id)
        if project.supervisor and project.supervisor != request.user:
            return HttpResponseForbidden("Bạn không có quyền chỉnh sửa dự án của Chỉ huy khác.")
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        start_date = request.POST.get('start_date')
        status = request.POST.get('status')
        supervisor_id = request.POST.get('supervisor')

        if not name:
            messages.error(request, "Tên dự án không được để trống.")
        else:
            project.name = name
            project.description = description
            if start_date:
                project.start_date = start_date
            if status:
                project.status = status
            
            if request.user.user_type == CustomUser.USER_TYPE_ADMIN and supervisor_id:
                project.supervisor_id = supervisor_id
            elif project.supervisor is None and request.user.user_type == CustomUser.USER_TYPE_SUPERVISOR:
                project.supervisor = request.user

            project.save()
            messages.success(request, f'Đã cập nhật thông tin chi tiết dự án "{project.name}" thành công!')
    
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or f'/projects/{project.id}/'
    return redirect(next_url)

@login_required
def alert_list(request):
    """
    Hiển thị danh sách Lịch sử sự cố & cảnh báo phát hiện cháy từ Camera UAV.
    Áp dụng phân quyền dữ liệu chặt chẽ (RBAC & Data Access Control):
    - Admin: Toàn quyền xem tất cả dự án.
    - Supervisor: Xem các sự cố thuộc dự án do mình chỉ huy.
    - Agent: Xem các sự cố thuộc dự án mình được phân công vận hành.
    """
    from .models import Alert, SystemSetting
    
    status_filter = request.GET.get('status', 'all')
    base_query = Alert.objects.select_related(
        'camera', 
        'camera__name_zone', 
        'camera__name_zone__name_project', 
        'reviewed_by',
        'session'
    )
    
    # Phân quyền dữ liệu theo vai trò người dùng
    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        user_alerts = base_query
    elif request.user.user_type == CustomUser.USER_TYPE_SUPERVISOR:
        user_alerts = base_query.filter(camera__name_zone__name_project__supervisor=request.user)
    elif request.user.user_type == CustomUser.USER_TYPE_AGENT:
        user_alerts = base_query.filter(camera__name_zone__assigned_agents__user=request.user)
    else:
        user_alerts = base_query.none()
    
    alerts_filtered = user_alerts
    if status_filter != 'all':
        alerts_filtered = alerts_filtered.filter(status=status_filter)
        
    alerts = alerts_filtered.order_by('-detected_at')
    
    total_count = user_alerts.count()
    new_count = user_alerts.filter(status=Alert.STATUS_NEW).count()
    confirmed_count = user_alerts.filter(status=Alert.STATUS_CONFIRMED).count()
    false_count = user_alerts.filter(status=Alert.STATUS_FALSE).count()
    ai_settings = SystemSetting.get_settings()
    
    return render(request, 'projects/alert_list.html', {
        'alerts': alerts,
        'status_filter': status_filter,
        'total_count': total_count,
        'new_count': new_count,
        'confirmed_count': confirmed_count,
        'false_count': false_count,
        'ai_settings': ai_settings,
    })

@login_required
def review_alert(request, alert_id):
    """
    Xử lý thẩm định cảnh báo: Chỉ huy bay (Supervisor) xác nhận 'confirmed' (Cháy thật) hoặc 'false_alarm' (Báo nhầm).
    Quản trị viên (Admin) và Người vận hành (Agent) chỉ có quyền giám sát/theo dõi, không có quyền can thiệp thẩm định thực địa.
    Đồng thời ghi nhận lịch sử vào AlertReview (Audit Trail) để không ghi đè dữ liệu đánh giá cũ.
    """
    from .models import Alert, AlertReview
    from django.utils import timezone
    from django.http import JsonResponse
    
    # Kiểm tra phân quyền chặt chẽ: Chỉ có Điều phối viên giám sát mới được thẩm định tác chiến
    if request.user.user_type != CustomUser.USER_TYPE_SUPERVISOR:
        error_msg = "Truy cập bị từ chối: Thao tác thẩm định thực địa thuộc thẩm quyền riêng của Điều phối viên giám sát. Quản trị viên hệ thống chỉ có quyền giám sát."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg}, status=403)
        return HttpResponseForbidden(error_msg)
    
    if request.method == 'POST':
        alert = get_object_or_404(Alert, id=alert_id)
        action = request.POST.get('action') # 'confirmed' or 'false_alarm'
        note = request.POST.get('note', '').strip()
        
        if action in [Alert.STATUS_CONFIRMED, Alert.STATUS_FALSE]:
            prev_status = alert.status
            alert.status = action
            alert.note = note
            alert.reviewed_by = request.user
            alert.reviewed_at = timezone.now()
            alert.save()
            
            # Ghi nhận Audit Trail
            AlertReview.objects.create(
                alert=alert,
                reviewed_by=request.user,
                previous_status=prev_status,
                new_status=action,
                action='confirm' if action == Alert.STATUS_CONFIRMED else 'reject',
                review_notes=note
            )
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                # Tính count theo phạm vi dự án của supervisor hiện tại
                sup_alerts = Alert.objects.filter(camera__name_zone__name_project__supervisor=request.user)
                return JsonResponse({
                    'success': True,
                    'alert_id': alert.id,
                    'status': alert.status,
                    'status_display': alert.get_status_display(),
                    'reviewer': alert.reviewed_by.email if alert.reviewed_by else '',
                    'new_count': sup_alerts.filter(status=Alert.STATUS_NEW).count(),
                    'confirmed_count': sup_alerts.filter(status=Alert.STATUS_CONFIRMED).count(),
                    'false_count': sup_alerts.filter(status=Alert.STATUS_FALSE).count(),
                    'total_count': sup_alerts.count()
                })
            
            if action == Alert.STATUS_CONFIRMED:
                messages.success(request, f"Đã XÁC NHẬN CHÁY THẬT cho cảnh báo #{alert.id} tại {alert.camera.name_cam}!")
            else:
                messages.warning(request, f"Đã đánh dấu BÁO NHẦM cho cảnh báo #{alert.id}.")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Thao tác không hợp lệ'}, status=400)
            messages.error(request, "Thao tác đánh giá không hợp lệ.")
            
    return redirect('projects:alert_list')


@login_required
def api_latest_alerts(request):
    """
    API JSON trả về dữ liệu sự cố mới nhất cho Supervisor và Admin theo thời gian thực (Real-time).
    Có kiểm tra phân quyền chặt chẽ (RBAC & Data Access Control).
    """
    from .models import Alert
    from django.http import JsonResponse
    
    status_filter = request.GET.get('status', 'all')
    base_query = Alert.objects.select_related(
        'camera', 
        'camera__name_zone', 
        'camera__name_zone__name_project', 
        'reviewed_by',
        'session'
    )
    
    # Phân quyền dữ liệu theo vai trò
    if request.user.user_type == CustomUser.USER_TYPE_ADMIN:
        user_alerts = base_query
    elif request.user.user_type == CustomUser.USER_TYPE_SUPERVISOR:
        user_alerts = base_query.filter(camera__name_zone__name_project__supervisor=request.user)
    elif request.user.user_type == CustomUser.USER_TYPE_AGENT:
        user_alerts = base_query.filter(camera__name_zone__assigned_agents__user=request.user)
    else:
        return JsonResponse({'success': False, 'error': 'Truy cập bị từ chối'}, status=403)
    
    alerts_query = user_alerts
    if status_filter != 'all':
        alerts_query = alerts_query.filter(status=status_filter)
        
    alerts_list = alerts_query.order_by('-detected_at')[:30]
    
    total_count = user_alerts.count()
    new_count = user_alerts.filter(status=Alert.STATUS_NEW).count()
    confirmed_count = user_alerts.filter(status=Alert.STATUS_CONFIRMED).count()
    false_count = user_alerts.filter(status=Alert.STATUS_FALSE).count()
    
    first_alert = user_alerts.order_by('-id').first()
    newest_id = first_alert.id if first_alert else 0
    
    data = []
    for a in alerts_list:
        data.append({
            'id': a.id,
            'detected_time': a.detected_at.strftime("%H:%M:%S"),
            'detected_date': a.detected_at.strftime("%d/%m/%Y"),
            'video_timestamp': a.video_timestamp,
            'session_code': a.session.session_code if a.session else '',
            'cam_id': a.camera.cam_ID if a.camera else None,
            'cam_name': a.camera.name_cam if a.camera else 'N/A',
            'zone_name': a.camera.name_zone.name_zone if (a.camera and a.camera.name_zone) else 'N/A',
            'project_name': a.camera.name_zone.name_project.name if (a.camera and a.camera.name_zone and a.camera.name_zone.name_project) else 'N/A',
            'evidence_url': f"/media/{a.evidence_image}" if a.evidence_image else '',
            'class_label': a.class_label,
            'confidence': a.confidence_percent,
            'status': a.status,
            'status_display': a.get_status_display(),
            'reviewer': a.reviewed_by.email if a.reviewed_by else '',
            'note': a.note or '',
        })
        
    return JsonResponse({
        'success': True,
        'newest_id': newest_id,
        'total_count': total_count,
        'new_count': new_count,
        'confirmed_count': confirmed_count,
        'false_count': false_count,
        'alerts': data
    })


@login_required
def api_ai_settings(request):
    """
    API cấu hình thông số nhận diện AI động (SystemSetting).
    - GET: Xem cấu hình hiện tại (Mọi tài khoản đăng nhập).
    - POST: Cập nhật ngưỡng (Chỉ dành cho Quản trị viên Admin hoặc Chỉ huy Supervisor).
    """
    from .models import SystemSetting
    from django.http import JsonResponse
    
    settings = SystemSetting.get_settings()
    
    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'fire_conf': settings.fire_conf,
            'smoke_conf': settings.smoke_conf,
            'persistence_frames': settings.persistence_frames,
            'gap_seconds': settings.gap_seconds,
            'updated_at': settings.updated_at.strftime("%H:%M:%S %d/%m/%Y") if settings.updated_at else '',
            'updated_by': settings.updated_by.email if settings.updated_by else 'Mặc định hệ thống'
        })
        
    elif request.method == 'POST':
        if request.user.user_type not in [CustomUser.USER_TYPE_ADMIN, CustomUser.USER_TYPE_SUPERVISOR]:
            return JsonResponse({'success': False, 'error': 'Chỉ có Admin hoặc Supervisor mới có quyền điều chỉnh thông số AI.'}, status=403)
            
        try:
            import json
            if request.content_type == 'application/json':
                body = json.loads(request.body)
            else:
                body = request.POST
                
            fire_conf = float(body.get('fire_conf', settings.fire_conf))
            smoke_conf = float(body.get('smoke_conf', settings.smoke_conf))
            persistence_frames = int(body.get('persistence_frames', settings.persistence_frames))
            gap_seconds = float(body.get('gap_seconds', settings.gap_seconds))
            
            # Validation
            if not (0.1 <= fire_conf <= 0.95 and 0.1 <= smoke_conf <= 0.95):
                return JsonResponse({'success': False, 'error': 'Ngưỡng tin cậy phải nằm trong khoảng từ 0.10 đến 0.95.'}, status=400)
            if not (1 <= persistence_frames <= 30):
                return JsonResponse({'success': False, 'error': 'Số khung hình duy trì phải từ 1 đến 30.'}, status=400)
            if not (3.0 <= gap_seconds <= 120.0):
                return JsonResponse({'success': False, 'error': 'Khoảng cách gom cụm sự cố phải từ 3 đến 120 giây.'}, status=400)
                
            settings.fire_conf = round(fire_conf, 2)
            settings.smoke_conf = round(smoke_conf, 2)
            settings.persistence_frames = persistence_frames
            settings.gap_seconds = round(gap_seconds, 1)
            settings.updated_by = request.user
            settings.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Đã cập nhật cấu hình AI thành công! Các luồng camera UAV đang hoạt động sẽ áp dụng ngay lập tức.',
                'fire_conf': settings.fire_conf,
                'smoke_conf': settings.smoke_conf,
                'persistence_frames': settings.persistence_frames,
                'gap_seconds': settings.gap_seconds
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Lỗi khi cập nhật cấu hình: {str(e)}'}, status=400)
            
    return JsonResponse({'success': False, 'error': 'Phương thức không được hỗ trợ'}, status=405)
