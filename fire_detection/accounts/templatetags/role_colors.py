from django import template

register = template.Library()

@register.simple_tag
def get_role_bg(user=None):
    """Đồng nhất màu nền thương hiệu hệ thống (Primary Blue) trên tất cả các trang"""
    return 'bg-primary'

@register.simple_tag
def get_role_text(user=None):
    """Đồng nhất màu chữ tiêu đề thương hiệu hệ thống (Primary Blue)"""
    return 'text-primary'

@register.simple_tag
def get_role_btn(user=None):
    """Đồng nhất nút bấm thao tác chính (btn-primary)"""
    return 'btn-primary'

@register.simple_tag
def get_role_badge(user=None):
    """Đồng nhất huy hiệu nhận diện (bg-primary)"""
    return 'bg-primary'
