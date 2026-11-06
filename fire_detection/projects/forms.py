from django import forms
from .models import Project
from agents.models import AgentProfile

class ProjectCreationForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            'name', 'description', 'start_date'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'Nhập tên dự án / chuyến bay tuần tra...',
                'class': 'form-control col-md-6'
            }),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Mục tiêu giám sát, đặc điểm khu rừng...'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.supervisor = kwargs.pop('supervisor', None)
        super().__init__(*args, **kwargs)
    
    def save(self, commit=True):
        project = super().save(commit=False)
        if self.supervisor:
            project.supervisor = self.supervisor
        
        if commit:
            project.save()
        
        return project