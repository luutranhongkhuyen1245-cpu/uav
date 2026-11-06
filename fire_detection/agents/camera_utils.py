# agents/camera_utils.py

import logging
import threading
import time
from pathlib import Path
import cv2
import torch
from django.conf import settings
from ultralytics import YOLO

# Configuration du logger
logger = logging.getLogger(__name__)

# Configuration du chemin de base du projet
BASE_DIR = Path(__file__).resolve().parent.parent

# Vérification de la disponibilité d'un GPU
device = 'cuda' if torch.cuda.is_available() else 'cpu'
logger.info(f'Utilisation du device: {device}')

# Recherche du modèle YOLO dans plusieurs emplacements possibles
MODEL_PATHS = [
    BASE_DIR / 'fire_smoke_best.pt',
    BASE_DIR / 'FireShield.pt',
    BASE_DIR / 'Hakim-F.pt',
    BASE_DIR / 'yolov8n.pt',
]

model = None
for path in MODEL_PATHS:
    if path and path.exists():
        try:
            model = YOLO(str(path)).to(device)
            logger.info(f'Modèle YOLO chargé avec succès depuis: {path}')
            break
        except Exception as e:
            logger.error(f'Erreur lors du chargement du modèle depuis {path}: {e}')

if model is None:
    logger.warning('Modèle YOLO non trouvé. La détection d\'objets sera désactivée.')
    logger.warning(f'Chemins vérifiés: {MODEL_PATHS}')


active_cameras = {}
active_fire_states = {}  # Lưu trữ cam_id: timestamp lần cuối phát hiện lửa/khói (debounce)

class VideoCamera:
    """
    Quản lý luồng video camera UAV với mô hình phát hiện lửa/khói YOLO.
    Hỗ trợ cấu hình động (SystemSetting), gom cụm cảnh báo theo video timestamp (CAP_PROP_POS_MSEC),
    lọc khung hình duy trì (persistence frames) và tự động nâng cấp sự cố (Khói -> Lửa & Khói).
    """
    def __init__(self, rtsp_url, cam_name, cam_id=None):
        self.rtsp_url = rtsp_url
        self.cam_name = cam_name
        self.cam_id = int(cam_id) if cam_id is not None and str(cam_id).isdigit() else cam_id
        
        # Cấu hình AI mặc định (sẽ được tự động đồng bộ từ SystemSetting)
        self.fire_conf = 0.45
        self.smoke_conf = 0.35
        self.persistence_frames = 3
        self.gap_seconds = 15.0
        self._last_settings_load_time = 0.0

        # Trạng thái phát hiện thời gian thực & bộ đệm persistence
        self.consecutive_detection_frames = 0
        self.consecutive_empty_frames = 0
        self.is_fire_detected = False
        self.last_fire_wall_time = 0.0
        self.active_alert_data = None

        # Trạng thái gom cụm sự cố theo Video Timestamp (Mốc thời gian clip UAV)
        self.last_video_sec = 0.0
        self.current_incident_alert_id = None
        self.current_incident_start_sec = 0.0
        self.current_incident_end_sec = 0.0
        self.current_incident_label = ''
        self.start_wall_time = time.time()

        if isinstance(self.rtsp_url, str):
            self.rtsp_url = self.rtsp_url.strip().strip('"').strip("'")
            p = Path(self.rtsp_url)
            self.is_file = p.suffix.lower() in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.m4v'] or p.is_file()
        else:
            self.is_file = False
        
        if self.cam_id:
            active_cameras[self.cam_id] = self

        video_source = int(self.rtsp_url) if str(self.rtsp_url).isdigit() else self.rtsp_url
        self.video = cv2.VideoCapture(video_source)
        self.fps = self.video.get(cv2.CAP_PROP_FPS) or 25.0
        if self.fps <= 0 or self.fps > 120:
            self.fps = 25.0

        self.grabbed, raw_frame = self.video.read()
        self.frame = self._resize_if_needed(raw_frame) if self.grabbed and raw_frame is not None else None
        self.running = True
        
        # Quản lý tự động kết nối lại
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5

        # Tải cấu hình AI ban đầu
        self.sync_system_settings()

        # Thread đọc khung hình nền
        threading.Thread(target=self.update, args=(), daemon=True).start()

    def _resize_if_needed(self, frame):
        """Giảm kích thước khung hình nếu độ phân giải quá cao (như 4K/2K) để tối ưu YOLO và streaming."""
        if frame is None:
            return None
        h, w = frame.shape[:2]
        max_w, max_h = 1280, 720
        if w > max_w or h > max_h:
            scale = min(max_w / w, max_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return frame

    def sync_system_settings(self):
        """Đồng bộ cấu hình AI động từ CSDL SystemSetting."""
        now = time.time()
        if now - self._last_settings_load_time < 3.0:
            return
        self._last_settings_load_time = now
        try:
            from projects.models import SystemSetting
            settings = SystemSetting.get_settings()
            self.fire_conf = settings.fire_conf
            self.smoke_conf = settings.smoke_conf
            self.persistence_frames = settings.persistence_frames
            self.gap_seconds = settings.gap_seconds
        except Exception as e:
            logger.debug(f"Không thể tải SystemSetting: {e}")

    def __del__(self):
        """Giải phóng tài nguyên camera khi đối tượng bị hủy."""
        logger.info(f"Giải phóng tài nguyên cho camera {self.cam_name}")
        self.running = False
        if hasattr(self, 'video') and self.video.isOpened():
            self.video.release()
        if hasattr(self, 'cam_id') and self.cam_id:
            if active_cameras.get(self.cam_id) is self:
                active_cameras.pop(self.cam_id, None)

    def trigger_new_incident(self, frame_bgr, conf, label, video_sec):
        """Khởi tạo một cảnh báo sự cố mới trong CSDL (theo cụm video timestamp)."""
        self.current_incident_end_sec = video_sec
        self.current_incident_start_sec = video_sec
        self.current_incident_label = label
        
        threading.Thread(
            target=self._save_new_alert,
            args=(frame_bgr, conf, label, video_sec),
            daemon=True
        ).start()

    def _save_new_alert(self, frame_bgr, conf, label, video_sec):
        try:
            from datetime import datetime
            from django.utils import timezone
            from django.conf import settings
            from projects.models import Cam, Alert, MonitoringSession

            cam = Cam.objects.filter(cam_ID=self.cam_id).first()
            if not cam:
                return

            # Tìm hoặc tạo phiên giám sát hoạt động
            session = MonitoringSession.objects.filter(camera=cam, status=MonitoringSession.STATUS_ACTIVE).first()
            if not session and cam.name_zone:
                session = MonitoringSession.objects.create(
                    project=cam.name_zone.name_project,
                    zone=cam.name_zone,
                    camera=cam,
                    status=MonitoringSession.STATUS_ACTIVE
                )

            evidences_dir = Path(settings.MEDIA_ROOT) / 'evidences'
            evidences_dir.mkdir(parents=True, exist_ok=True)

            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"snapshot_cam_{self.cam_id}_{timestamp_str}.jpg"
            file_path = evidences_dir / filename
            cv2.imwrite(str(file_path), frame_bgr)

            conf_val = round(conf * 100.0, 1) if conf <= 1.0 else round(conf, 1)
            rel_path = f"evidences/{filename}"

            alert = Alert.objects.create(
                camera=cam,
                session=session,
                video_timestamp=round(video_sec, 2),
                class_label=label,
                confidence_score=conf_val,
                evidence_image=rel_path,
                status=Alert.STATUS_NEW
            )

            self.current_incident_alert_id = alert.id
            self.active_alert_data = {
                'id': alert.id,
                'label': alert.class_label,
                'confidence': f"{conf_val}%",
                'time': timezone.localtime(alert.detected_at).strftime("%H:%M:%S"),
                'video_time': f"{int(video_sec)}s",
                'evidence_url': f"/media/{rel_path}"
            }

            if session:
                session.total_alerts += 1
                session.save(update_fields=['total_alerts'])

            logger.info(f"[ALERT CREATED] Alert #{alert.id} | Cam={self.cam_name} | Label={label} | VideoSec={video_sec:.1f}s | Conf={conf_val}%")
        except Exception as e:
            logger.error(f"Lỗi khi lưu sự cố mới: {e}", exc_info=True)

    def escalate_current_incident(self, frame_bgr, conf, label, video_sec):
        """Nâng cấp sự cố đang diễn ra (ví dụ: Khói phát triển thành Khói & Lửa)."""
        self.current_incident_label = label
        alert_id = self.current_incident_alert_id
        if not alert_id:
            return

        threading.Thread(
            target=self._escalate_alert,
            args=(alert_id, frame_bgr, conf, label, video_sec),
            daemon=True
        ).start()

    def _escalate_alert(self, alert_id, frame_bgr, conf, label, video_sec):
        try:
            from datetime import datetime
            from django.utils import timezone
            from django.conf import settings
            from projects.models import Alert

            alert = Alert.objects.filter(id=alert_id).first()
            if not alert:
                return

            evidences_dir = Path(settings.MEDIA_ROOT) / 'evidences'
            evidences_dir.mkdir(parents=True, exist_ok=True)
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"escalate_cam_{self.cam_id}_{timestamp_str}.jpg"
            file_path = evidences_dir / filename
            cv2.imwrite(str(file_path), frame_bgr)

            conf_val = round(conf * 100.0, 1) if conf <= 1.0 else round(conf, 1)
            rel_path = f"evidences/{filename}"

            alert.class_label = label
            if conf_val > alert.confidence_score:
                alert.confidence_score = conf_val
            alert.evidence_image = rel_path
            alert.note = f"Tự động nâng cấp lúc video {int(video_sec)}s: Phát hiện bùng phát lửa sau khói."
            alert.save(update_fields=['class_label', 'confidence_score', 'evidence_image', 'note'])

            self.active_alert_data = {
                'id': alert.id,
                'label': alert.class_label,
                'confidence': f"{alert.confidence_percent}%",
                'time': timezone.localtime(alert.detected_at).strftime("%H:%M:%S"),
                'video_time': f"{int(video_sec)}s",
                'evidence_url': f"/media/{rel_path}"
            }
            logger.info(f"[ALERT ESCALATED] Alert #{alert.id} nâng cấp thành '{label}' tại video {video_sec:.1f}s")
        except Exception as e:
            logger.error(f"Lỗi khi nâng cấp sự cố: {e}", exc_info=True)

    def get_active_alert_info(self):
        """Trả về thông tin sự cố đang kích hoạt cảnh báo cho API polling."""
        return self.active_alert_data

    def get_frame(self):
        """
        Trích xuất một khung hình, chạy phát hiện YOLO theo cấu hình động,
        áp dụng gom cụm Video Timestamp và trả về JPEG bytes.
        """
        if not self.grabbed or self.frame is None:
            return None

        try:
            # Clone frame để xử lý an toàn đa luồng
            frame_to_process = self.frame.copy()

            # Đồng bộ cấu hình AI định kỳ từ CSDL
            self.sync_system_settings()

            # Tính mốc thời gian trong video UAV (giây)
            video_sec = self.video.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if video_sec <= 0:
                fps = self.fps or 25.0
                frame_pos = self.video.get(cv2.CAP_PROP_POS_FRAMES)
                video_sec = (frame_pos / fps) if fps > 0 else (time.time() - self.start_wall_time)

            # Phát hiện video lặp lại (Loop) -> Reset sạch trạng thái cụm cảnh báo cho vòng lặp mới
            if self.last_video_sec > 5.0 and video_sec < (self.last_video_sec - 5.0):
                logger.info(f"[VIDEO LOOP] Camera {self.cam_name}: Video đã phát lại từ đầu ({video_sec:.1f}s < {self.last_video_sec:.1f}s). Reset trạng thái gom cụm.")
                self.current_incident_alert_id = None
                self.current_incident_end_sec = 0.0
                self.consecutive_detection_frames = 0
            self.last_video_sec = video_sec

            if model:
                min_conf = min(self.fire_conf, self.smoke_conf)
                results = model.predict(frame_to_process, conf=min_conf, verbose=False)
                res_plotted = results[0].plot()
                boxes = results[0].boxes

                has_fire = False
                has_smoke = False
                max_fire_conf = 0.0
                max_smoke_conf = 0.0

                for b in boxes:
                    c_id = int(b.cls[0].item())
                    c_name = str(model.names.get(c_id, '')).lower()
                    c_conf = float(b.conf[0].item())

                    if 'fire' in c_name and c_conf >= self.fire_conf:
                        has_fire = True
                        max_fire_conf = max(max_fire_conf, c_conf)
                    elif 'smoke' in c_name and c_conf >= self.smoke_conf:
                        has_smoke = True
                        max_smoke_conf = max(max_smoke_conf, c_conf)

                is_detected_in_frame = has_fire or has_smoke

                if is_detected_in_frame:
                    self.consecutive_detection_frames += 1
                    self.consecutive_empty_frames = 0
                else:
                    self.consecutive_empty_frames += 1
                    self.consecutive_detection_frames = max(0, self.consecutive_detection_frames - 1)

                # Kiểm tra điều kiện duy trì (Persistence frames)
                is_persistent = (self.consecutive_detection_frames >= self.persistence_frames)

                if is_persistent:
                    self.is_fire_detected = True
                    self.last_fire_wall_time = time.time()
                    if self.cam_id:
                        active_fire_states[self.cam_id] = self.last_fire_wall_time
                        active_cameras[self.cam_id] = self

                    max_conf = max(max_fire_conf, max_smoke_conf)
                    if has_fire and has_smoke:
                        current_label = 'Lửa & Khói (Fire & Smoke)'
                    elif has_fire:
                        current_label = 'Lửa (Fire)'
                    else:
                        current_label = 'Khói (Smoke)'

                    # Kiểm tra gom cụm sự cố theo Video Timestamp:
                    # Nếu chưa có sự cố hoặc khoảng lặng video vượt quá gap_seconds -> tạo sự cố mới
                    is_new_incident = (
                        self.current_incident_alert_id is None or 
                        (video_sec - self.current_incident_end_sec > self.gap_seconds)
                    )

                    if is_new_incident:
                        self.trigger_new_incident(res_plotted.copy(), max_conf, current_label, video_sec)
                    else:
                        # Vẫn trong cùng sự cố: Cập nhật mốc kết thúc
                        self.current_incident_end_sec = video_sec
                        # Nâng cấp nếu trước đó chỉ có khói và bây giờ phát hiện thêm lửa
                        if has_fire and ('Lửa' not in self.current_incident_label):
                            self.escalate_current_incident(res_plotted.copy(), max_conf, current_label, video_sec)
                else:
                    # Debounce 5s để tránh chớp nháy tắt cảnh báo nếu mất dấu 1-2 frames
                    if (time.time() - getattr(self, 'last_fire_wall_time', 0)) < 5.0:
                        self.is_fire_detected = True
                    else:
                        self.is_fire_detected = False
                        if self.cam_id and self.cam_id in active_fire_states:
                            if time.time() - active_fire_states.get(self.cam_id, 0) > 5.0:
                                active_fire_states.pop(self.cam_id, None)
            else:
                res_plotted = frame_to_process

            _, jpeg = cv2.imencode('.jpg', res_plotted, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return jpeg.tobytes()

        except Exception as e:
            logger.error(f'Lỗi khi xử lý frame camera {self.cam_name}: {e}')
            return None

    def update(self):
        """
        Met à jour le flux vidéo en continu dans un thread séparé.
        """
        while self.running:
            if not self.video.isOpened():
                logger.warning(f"Le flux vidéo pour {self.cam_name} n'est pas ouvert. Tentative de reconnexion.")
                self.reconnect()
                time.sleep(1)
                continue

            try:
                grabbed, frame = self.video.read()
                if not grabbed:
                    # If reading a video file, loop back to the beginning
                    if self.is_file:
                        self.video.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        grabbed, frame = self.video.read()

                    if not grabbed:
                        logger.warning(f'Impossible de lire une frame depuis {self.rtsp_url}')
                        self.reconnect()
                    else:
                        self.frame = self._resize_if_needed(frame)
                        self.grabbed = grabbed
                        self.reconnect_attempts = 0
                else:
                    self.frame = self._resize_if_needed(frame)
                    self.grabbed = grabbed
                    self.reconnect_attempts = 0
            except Exception as e:
                logger.error(f'Erreur lors de la lecture du flux pour {self.cam_name}: {e}')
                self.reconnect()
            
            # Điều tiết tốc độ khung hình phù hợp nguồn video
            if self.is_file:
                time.sleep(max(0.015, 1.0 / self.fps))
            else:
                time.sleep(0.01)

    def reconnect(self):
        """
        Tente de se reconnecter à la caméra en cas d'erreur.
        """
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f'Nombre maximal de tentatives de reconnexion atteint pour {self.cam_name}. Arrêt du flux.')
            self.running = False
            return
            
        self.reconnect_attempts += 1
        logger.info(f'Tentative de reconnexion {self.reconnect_attempts}/{self.max_reconnect_attempts} pour {self.cam_name} dans {self.reconnect_delay}s...')
        
        time.sleep(self.reconnect_delay)
        
        try:
            if self.video.isOpened():
                self.video.release()
            clean_url = str(self.rtsp_url).strip().strip('"').strip("'")
            video_source = int(clean_url) if clean_url.isdigit() else clean_url
            self.video = cv2.VideoCapture(video_source)
            grabbed, frame = self.video.read()
            if grabbed:
                logger.info(f'Reconnexion réussie pour {self.cam_name}')
                self.frame = self._resize_if_needed(frame)
                self.grabbed = grabbed
                self.reconnect_attempts = 0
        except Exception as e:
            logger.error(f'Erreur lors de la reconnexion à {self.cam_name}: {e}')


def gen(camera):
    """
    Générateur cho luồng video multipart HTTP streaming.
    """
    try:
        while camera.running:
            frame = camera.get_frame()
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
            else:
                time.sleep(0.04)
    except GeneratorExit:
        logger.debug(f'Client ngắt kết nối khỏi stream {camera.cam_name}')
    except Exception as e:
        logger.error(f'Lỗi luồng stream camera {camera.cam_name}: {e}')
