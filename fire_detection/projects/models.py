from django.db import models
from accounts.models import CustomUser
from agents.models import AgentProfile
from django.core.validators import MinValueValidator, MaxValueValidator
import django.utils.timezone

class Project(models.Model):
    STATUS_PLANNED = 'planned'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    # Aliases for compatibility
    STATUS_ACTIVE = 'in_progress'
    STATUS_INACTIVE = 'completed'

    STATUS_CHOICES = [
        ('planned', 'Đã lên kế hoạch'),
        ('in_progress', 'Đang tuần tra'),
        ('completed', 'Đã hoàn thành'),
        ('cancelled', 'Đã hủy'),
        ('active', 'Đang hoạt động'),
        ('inactive', 'Tạm dừng'),
    ]
    
    # Informations de base
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Dates (SEULEMENT start_date)
    start_date = models.DateField(default=django.utils.timezone.now)  # ← CE CHAMP DOIT EXISTER
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Statut
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    
    # Relations
    supervisor = models.ForeignKey(
        CustomUser, 
        on_delete=models.SET_NULL,
        limit_choices_to={'user_type': CustomUser.USER_TYPE_SUPERVISOR},
        related_name='supervised_projects',
        null=True,
        blank=True
    )

    @property
    def assigned_agents(self):
        """
        Tập hợp tất cả Chuyên viên UAV phụ trách các phân khu thuộc Dự án này.
        """
        from agents.models import AgentProfile
        return AgentProfile.objects.filter(assigned_zones__name_project=self).distinct()
    
    def __str__(self):
        return self.name

    def get_progress_status(self):
        """
        Tính toán trạng thái tiến độ thông minh (Pipeline Status) cho Dự án:
        1. 'cancelled': Dự án đã bị hủy
        2. 'no_zones': Chưa vẽ vùng bay tuần tra (Cần vẽ phân khu)
        3. 'no_cams': Đã có vùng nhưng chưa gắn Camera UAV (Cần cấu hình UAV)
        4. 'patrolling': Đang tuần tra Live trên thực địa
        5. 'completed': Dự án đã hoàn thành / kết thúc
        6. 'ready': Đã sẵn sàng bay (Đã có đủ vùng + UAV)
        """
        if self.status == 'cancelled':
            return {
                'code': 'cancelled',
                'label': 'Đã hủy',
                'badge_class': 'bg-dark text-white',
                'icon': 'bi-x-circle-fill',
                'can_patrol': False,
                'is_live': False,
            }

        zones_count = self.zones.count()
        if zones_count == 0:
            return {
                'code': 'no_zones',
                'label': 'Chưa vẽ vùng bay',
                'badge_class': 'bg-warning-subtle text-warning-emphasis border border-warning',
                'icon': 'bi-exclamation-triangle-fill',
                'can_patrol': False,
                'is_live': False,
            }

        total_cams = sum(z.cameras.count() for z in self.zones.all())
        if total_cams == 0:
            return {
                'code': 'no_cams',
                'label': 'Chưa gắn UAV',
                'badge_class': 'bg-info-subtle text-info-emphasis border border-info',
                'icon': 'bi-camera-video-fill',
                'can_patrol': False,
                'is_live': False,
            }

        if self.status in ['in_progress', 'active']:
            return {
                'code': 'patrolling',
                'label': 'Đang tuần tra Live',
                'badge_class': 'badge-patrol-live',
                'icon': 'bi-record-circle-fill',
                'can_patrol': True,
                'is_live': True,
            }
        elif self.status == 'completed':
            return {
                'code': 'completed',
                'label': 'Đã hoàn thành',
                'badge_class': 'bg-secondary text-white',
                'icon': 'bi-check-all',
                'can_patrol': False,
                'is_live': False,
            }
        else:
            return {
                'code': 'ready',
                'label': 'Sẵn sàng bay',
                'badge_class': 'bg-success text-white',
                'icon': 'bi-check-circle-fill',
                'can_patrol': True,
                'is_live': False,
            }

    @property
    def progress_status(self):
        return self.get_progress_status()

    @property
    def first_zone(self):
        return self.zones.first()

    @property
    def total_cams_count(self):
        return sum(z.cameras.count() for z in self.zones.all())
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Project"
        verbose_name_plural = "Projects"

class Zone(models.Model):
    Zone_ID = models.AutoField(primary_key=True)
    name_zone = models.CharField(max_length=100)
    coords_polys = models.JSONField(null=True, blank=True)    
    description_zone = models.TextField(null=True, blank=True)
    name_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='zones')
    assigned_agents = models.ManyToManyField(
        AgentProfile,
        related_name='assigned_zones',
        blank=True,
        verbose_name="Người vận hành UAV phụ trách phân khu"
    )

    @property
    def active_camera(self):
        """Camera UAV đang trực chiến (bay chính) của phân khu."""
        cam = self.cameras.filter(is_primary=True).first()
        if not cam:
            cam = self.cameras.first()
            if cam:
                Cam.objects.filter(pk=cam.pk).update(is_primary=True)
                cam.is_primary = True
        return cam

    @property
    def standby_cameras(self):
        """Danh sách các Camera UAV dự phòng của phân khu."""
        active = self.active_camera
        if not active:
            return self.cameras.none()
        return self.cameras.exclude(cam_ID=active.cam_ID)

    def __str__(self):
        return f"{self.name_zone} du projet {self.name_project.name}"
# -------------- Model Cam ---------------------------
class Cam(models.Model):
    cam_ID = models.AutoField(primary_key=True)
    name_cam = models.CharField(max_length=100) 
    coords_cam = models.JSONField(null=True, blank=True)
    adresse_cam = models.GenericIPAddressField(null=True, blank=True)
    num_port = models.PositiveIntegerField(null=True,blank=True, 
    validators=[MinValueValidator(1), MaxValueValidator(65535)])
    rest_de_path = models.CharField(max_length=200, null=True, blank=True)
    description_cam = models.TextField(null=True, blank=True)
    custom_url = models.TextField(null=True, blank=True)
    is_full_rtsp_url = models.BooleanField(default=False)
    is_primary = models.BooleanField(default=False, verbose_name="UAV Trực chiến (Bay chính)")
    name_zone = models.ForeignKey(Zone, on_delete=models.CASCADE, related_name='cameras')

    def save(self, *args, **kwargs):
        # Nếu là camera đầu tiên của phân khu, tự động chuyển thành UAV Trực chiến
        if not self.pk:
            if not Cam.objects.filter(name_zone=self.name_zone).exists():
                self.is_primary = True

        super().save(*args, **kwargs)

        if self.is_primary:
            # Đảm bảo chỉ có 1 camera trực chiến duy nhất trong phân khu này
            Cam.objects.filter(name_zone=self.name_zone).exclude(pk=self.pk).update(is_primary=False)
        else:
            # Nếu phân khu chưa có camera trực chiến nào, tự động chọn camera đầu tiên
            if not Cam.objects.filter(name_zone=self.name_zone, is_primary=True).exists():
                first_cam = Cam.objects.filter(name_zone=self.name_zone).first()
                if first_cam:
                    Cam.objects.filter(pk=first_cam.pk).update(is_primary=True)

    def __str__(self):
        role_label = "Trực chiến" if self.is_primary else "Dự phòng"
        return f"{self.name_cam} [{role_label}] (zone : {self.name_zone.name_zone}, projet : {self.name_zone.name_project.name})"
    
    @property
    def rtsp_url(self):
        """
        Génère l'URL RTSP complète de la caméra.
        Utilise custom_url si is_full_rtsp_url est True, sinon construit l'URL.
        """
        if self.is_full_rtsp_url and self.custom_url:
            return self.custom_url
        
        if self.adresse_cam and self.num_port and self.rest_de_path:
            return f"rtsp://{self.adresse_cam}:{self.num_port}/{self.rest_de_path}"
        
        return None
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        if self.is_full_rtsp_url:
            if not self.custom_url:
                raise ValidationError({
                    'custom_url': 'Une URL personnalisée est requise.'
                })
        else:  # ← Ajouter ce else
            if not all([self.adresse_cam, self.num_port, self.rest_de_path]):
                raise ValidationError(
                    'Adresse IP, port et chemin sont requis.'
                )

# -------------- Model Cấu hình Hệ thống AI ---------------------------
class SystemSetting(models.Model):
    """
    Cấu hình hệ thống động cho AI nhận diện và cảnh báo lửa/khói UAV.
    Cho phép Supervisor và Admin tùy chỉnh trực tiếp trên giao diện mà không cần sửa code cứng hay restart server.
    """
    fire_conf = models.FloatField(default=0.45, verbose_name="Ngưỡng tin cậy Lửa (Fire)")
    smoke_conf = models.FloatField(default=0.35, verbose_name="Ngưỡng tin cậy Khói (Smoke)")
    persistence_frames = models.PositiveIntegerField(default=3, verbose_name="Số khung hình duy trì liên tiếp")
    gap_seconds = models.FloatField(default=15.0, verbose_name="Khoảng cách gom cụm video (giây)")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Cấu hình Hệ thống AI"
        verbose_name_plural = "Cấu hình Hệ thống AI"

    @classmethod
    def get_settings(cls):
        setting = cls.objects.first()
        if not setting:
            setting = cls.objects.create(
                fire_conf=0.45,
                smoke_conf=0.35,
                persistence_frames=3,
                gap_seconds=15.0
            )
        return setting

    def __str__(self):
        return f"AI Config (Fire: {self.fire_conf}, Smoke: {self.smoke_conf}, Persistence: {self.persistence_frames}f, Gap: {self.gap_seconds}s)"


# -------------- Model Quản lý Phiên Giám sát UAV ---------------------------
class MonitoringSession(models.Model):
    """
    Quản lý phiên giám sát / chuyến bay tuần tra UAV.
    Liên kết cảnh báo với phiên xử lý cụ thể để phục vụ thống kê và audit.
    """
    STATUS_ACTIVE = 'active'
    STATUS_COMPLETED = 'completed'
    STATUS_STOPPED = 'stopped'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Đang giám sát'),
        (STATUS_COMPLETED, 'Đã hoàn thành'),
        (STATUS_STOPPED, 'Đã dừng'),
    ]

    session_code = models.CharField(max_length=50, unique=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='monitoring_sessions', null=True, blank=True)
    zone = models.ForeignKey(Zone, on_delete=models.SET_NULL, null=True, blank=True, related_name='monitoring_sessions')
    camera = models.ForeignKey(Cam, on_delete=models.SET_NULL, null=True, blank=True, related_name='monitoring_sessions')
    operator = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='operated_sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    total_alerts = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']

    def save(self, *args, **kwargs):
        if not self.session_code:
            import uuid
            self.session_code = f"SES-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        cam_name = self.camera.name_cam if self.camera else "UAV"
        return f"Phiên {self.session_code} - {cam_name} ({self.get_status_display()})"


# -------------- Model Alert ---------------------------
class Alert(models.Model):
    STATUS_NEW = 'new'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_FALSE = 'false_alarm'
    STATUS_CHOICES = [
        (STATUS_NEW, 'Chờ xác nhận'),
        (STATUS_CONFIRMED, 'Xác nhận cháy thật'),
        (STATUS_FALSE, 'Báo nhầm'),
    ]

    camera = models.ForeignKey(Cam, on_delete=models.CASCADE, related_name='alerts')
    session = models.ForeignKey(MonitoringSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='alerts')
    video_timestamp = models.FloatField(null=True, blank=True, help_text="Thời điểm phát hiện trong video UAV (giây)")
    detected_at = models.DateTimeField(auto_now_add=True)
    class_label = models.CharField(max_length=50, default='Fire')
    confidence_score = models.FloatField(default=0.0)
    evidence_image = models.CharField(max_length=500, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    note = models.TextField(blank=True, default='')
    reviewed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_alerts')
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-detected_at']

    @property
    def confidence_percent(self):
        if self.confidence_score is None:
            return 0.0
        val = float(self.confidence_score)
        if val <= 1.0:
            val = val * 100.0
        return round(val, 1)

    def __str__(self):
        return f"Alert {self.id}: {self.class_label} ({self.confidence_percent}%) at {self.camera.name_cam}"


# -------------- Model AlertReview (Lịch sử thẩm định) ---------------------------
class AlertReview(models.Model):
    """
    Lịch sử thẩm định sự cố (Audit Trail).
    Ghi nhận mỗi lần Supervisor/Admin cập nhật trạng thái sự cố, lưu lịch sử đánh giá không bị ghi đè.
    """
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='reviews')
    reviewed_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='alert_reviews')
    previous_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    action = models.CharField(max_length=50, blank=True, default='')
    review_notes = models.TextField(blank=True, default='')
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-reviewed_at']

    def __str__(self):
        reviewer = self.reviewed_by.email if self.reviewed_by else "Hệ thống"
        return f"Audit Alert #{self.alert_id} bởi {reviewer}: {self.previous_status} -> {self.new_status}"
