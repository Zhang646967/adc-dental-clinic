"""Legacy HTTP scenarios now complete the REAL role/scope selection setup.
This helper does not disable middleware. v0.7 boundary tests use plain Client.
"""
from django.test import Client
from django.urls import reverse
from workspaces.context import SESSION_KEY, available_roles, authorized_clinics, token_for
from workspaces.models import WorkspaceContext

class WorkspaceClient(Client):
    def current_token(self):
        key=self.session.get(SESSION_KEY)
        ctx=WorkspaceContext.objects.filter(pk=key).first() if key else None
        return token_for(ctx) if ctx else ''
    def force_login(self,user,backend=None):
        super().force_login(user,backend=backend)
        # A new login should not inherit an old selected identity.
        session=self.session;session.pop(SESSION_KEY,None);session.save()
        self.get(reverse('select_role'))
        roles=available_roles(user)
        if not roles:return
        role=roles[0]
        # force_login is trusted fixture setup; model the selected HTTP channel
        # before exercising the real role/clinic activation boundary.
        ctx=WorkspaceContext.objects.get(pk=self.session[SESSION_KEY])
        ctx.login_channel='PATIENT' if role=='PATIENT' else 'STAFF'
        ctx.save(update_fields=['login_channel'])
        csrf=self.cookies['csrftoken'].value if 'csrftoken' in self.cookies else ''
        r=self.post(reverse('activate_role'),{'role':role,'csrfmiddlewaretoken':csrf})
        if r.status_code!=302:raise AssertionError(f'Role setup failed: {r.status_code}')
        clinics=authorized_clinics(user,role)
        if clinics.exists():
            r=self.post(reverse('activate_clinic'),{'clinic':clinics.first().pk,'csrfmiddlewaretoken':csrf})
            if r.status_code!=302:raise AssertionError(f'Clinic setup failed: {r.status_code}')
    def post(self,path,data=None,content_type=None,**extra):
        token=self.current_token()
        if content_type=='application/json':
            extra.setdefault('HTTP_X_ADC_WORKSPACE',token)
        elif isinstance(data,dict) or data is None:
            data=dict(data or {});data.setdefault('workspace_token',token)
        if content_type:extra['content_type']=content_type
        return super().post(path,data=data,**extra)
