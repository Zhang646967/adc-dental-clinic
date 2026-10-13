from django.urls import reverse
from guidance.catalog import GUIDES,choose_guide,VERSION

def navigation_answer(user,intent,message):
    ctx=getattr(user,'_adc_workspace',None)
    if ctx is None:return None # Existing internal caller contract; HTTP always carries context.
    key=choose_guide(ctx.role,intent,message)
    g=GUIDES.get(key)
    if g and ctx.role in g.roles:
        return {'title':g.title,'answer':g.goal+' 请打开下面的逐步指南，按顺序亲自操作。',
            'facts':[f'{i+1}. {s.instruction}' for i,s in enumerate(g.steps)],
            'links':[{'label':'开始逐步引导','url':reverse('guide_task',args=[g.key])}],
            'source':VERSION+' · 已核对页面与按钮目录','guide_id':g.key}
    if intent=='clinical':return None
    return {'title':'先确定你想办理哪件事','answer':'当前身份的操作指南列在帮助中心。如果要执行其他岗位的任务，请先切换到账号已有的对应身份；切换不会增加权限。',
        'facts':[],'links':[{'label':'查看当前身份的任务','url':reverse('guide_index')},{'label':'选择其他已授权身份','url':reverse('select_role')}],
        'source':VERSION+' · 不猜测目标页面或越权操作'}
