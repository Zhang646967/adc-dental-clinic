from django import template
from django.utils.html import format_html
from workspaces.context import token_for
register=template.Library()
@register.simple_tag(takes_context=True)
def workspace_token(context):
    request=context.get('request')
    ctx=getattr(request,'workspace',None)
    return format_html('<input type="hidden" name="workspace_token" value="{}">', token_for(ctx)) if ctx else ''
